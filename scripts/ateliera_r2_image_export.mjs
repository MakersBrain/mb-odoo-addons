import { createHash, createHmac } from 'node:crypto';
import { mkdir, writeFile } from 'node:fs/promises';
import { basename, join } from 'node:path';

const tenantId = process.argv[2];
const outputDirectory = process.argv[3];
if (!/^[0-9a-f-]{36}$/.test(tenantId || '') || !outputDirectory?.startsWith('/tmp/ateliera-r2-image-export-')) {
	throw new Error('usage: node ateliera_r2_image_export.mjs TENANT_UUID /tmp/ateliera-r2-image-export-UUID');
}

const cfg = {
	bucket: process.env.FILES_BUCKET,
	endpoint: process.env.FILES_ENDPOINT,
	accessKeyId: process.env.FILES_ACCESS_KEY_ID,
	secretAccessKey: process.env.FILES_SECRET_ACCESS_KEY,
	region: process.env.FILES_REGION || 'auto',
};
if (!cfg.bucket || !cfg.endpoint || !cfg.accessKeyId || !cfg.secretAccessKey) {
	throw new Error('Ateliera R2 configuration is incomplete');
}

function hmac(key, value) {
	return createHmac('sha256', key).update(value, 'utf8').digest();
}

function hash(value) {
	return createHash('sha256').update(value).digest('hex');
}

function signingKey(secret, stamp, region) {
	return hmac(hmac(hmac(hmac(`AWS4${secret}`, stamp), region), 's3'), 'aws4_request');
}

function encode(value) {
	return encodeURIComponent(value).replace(/[!'()*]/g, (character) => `%${character.charCodeAt(0).toString(16).toUpperCase()}`);
}

function canonicalPath(path) {
	return `/${cfg.bucket}${path.split('/').map((segment) => encode(segment)).join('/')}`;
}

function decodeXml(value) {
	return value.replaceAll('&amp;', '&').replaceAll('&lt;', '<').replaceAll('&gt;', '>').replaceAll('&quot;', '"').replaceAll('&apos;', "'");
}

async function signedGet(path, queryValues = []) {
	const now = new Date();
	const date = now.toISOString().replace(/[:-]|\.\d{3}/g, '');
	const stamp = date.slice(0, 8);
	const host = new URL(cfg.endpoint).host;
	const query = queryValues.sort(([left], [right]) => left.localeCompare(right)).map(([key, value]) => `${encode(key)}=${encode(value)}`).join('&');
	const payloadHash = hash('');
	const headers = `host:${host}\nx-amz-content-sha256:${payloadHash}\nx-amz-date:${date}\n`;
	const signedHeaders = 'host;x-amz-content-sha256;x-amz-date';
	const canonical = `GET\n${canonicalPath(path)}\n${query}\n${headers}\n${signedHeaders}\n${payloadHash}`;
	const scope = `${stamp}/${cfg.region}/s3/aws4_request`;
	const stringToSign = `AWS4-HMAC-SHA256\n${date}\n${scope}\n${hash(canonical)}`;
	const signature = createHmac('sha256', signingKey(cfg.secretAccessKey, stamp, cfg.region)).update(stringToSign).digest('hex');
	return fetch(`${cfg.endpoint}/${cfg.bucket}${path}${query ? `?${query}` : ''}`, { headers: {
		'authorization': `AWS4-HMAC-SHA256 Credential=${cfg.accessKeyId}/${scope}, SignedHeaders=${signedHeaders}, Signature=${signature}`,
		'x-amz-content-sha256': payloadHash,
		'x-amz-date': date,
	} });
}

async function listProductObjects() {
	const objects = [];
	let token = null;
	do {
		const query = [['list-type', '2'], ['max-keys', '1000'], ['prefix', `t/${tenantId}/products/`]];
		if (token) query.push(['continuation-token', token]);
		const response = await signedGet('', query);
		const xml = await response.text();
		if (!response.ok) throw new Error(`R2 list failed ${response.status}: ${xml.slice(0, 300)}`);
		objects.push(...[...xml.matchAll(/<Contents>.*?<Key>(.*?)<\/Key>.*?<Size>(\d+)<\/Size>.*?<\/Contents>/gs)].map((match) => ({
			key: decodeXml(match[1]), bytes: Number(match[2]),
		})));
		token = xml.match(/<NextContinuationToken>(.*?)<\/NextContinuationToken>/s)?.[1];
		token = token ? decodeXml(token) : null;
	} while (token);
	return objects;
}

function renditionPriority(key) {
	if (key.includes('@original-')) return 3;
	if (key.includes('@display-')) return 2;
	if (key.includes('@thumb-')) return 1;
	return 0;
}

function extension(key) {
	const value = key.split('.').at(-1)?.toLowerCase();
	if (!['jpg', 'jpeg', 'png', 'webp', 'gif'].includes(value)) throw new Error(`unsupported image extension: ${key}`);
	return value === 'jpeg' ? 'jpg' : value;
}

const objects = await listProductObjects();
const { S3Storage } = await import('/app/apps/api/src/files/storage.ts');
const storage = new S3Storage();
const selected = new Map();
for (const object of objects) {
	const match = object.key.match(new RegExp(`^t/${tenantId}/products/([^/]+)/`));
	if (!match) continue;
	const current = selected.get(match[1]);
	if (!current || renditionPriority(object.key) > renditionPriority(current.key) || (
		renditionPriority(object.key) === renditionPriority(current.key) && object.bytes > current.bytes
	)) selected.set(match[1], object);
}

await mkdir(outputDirectory, { recursive: false });
const manifest = [];
for (const [productUid, object] of [...selected.entries()].sort()) {
	if (object.bytes <= 0 || object.bytes > 20_000_000) throw new Error(`unsafe image size for ${object.key}`);
	const stored = await storage.get(object.key);
	if (!stored) throw new Error(`R2 object disappeared: ${object.key}`);
	const chunks = [];
	for await (const chunk of stored.stream) chunks.push(Buffer.from(chunk));
	const bytes = Buffer.concat(chunks);
	if (bytes.length !== object.bytes) throw new Error(`R2 size mismatch: ${object.key}`);
	const sha256 = hash(bytes);
	const shortDigest = object.key.match(/-([0-9a-f]{12})\.[^.]+$/)?.[1];
	if (!shortDigest || !sha256.startsWith(shortDigest)) throw new Error(`R2 digest mismatch: ${object.key}`);
	const filename = `${productUid}.${extension(object.key)}`;
	await writeFile(join(outputDirectory, filename), bytes);
	manifest.push({ productUid, filename, objectKey: object.key, bytes: bytes.length, sha256 });
}
await writeFile(join(outputDirectory, 'manifest.json'), JSON.stringify({ tenantId, objects: objects.length, images: manifest }, null, 2));
console.log(JSON.stringify({ tenantId, renditions: objects.length, products: manifest.length, bytes: manifest.reduce((sum, image) => sum + image.bytes, 0), directory: basename(outputDirectory) }));
