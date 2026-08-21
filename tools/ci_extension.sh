#!/bin/sh
set -eu

# Build and materialize the same transport image the release workflow ships.
# The caller owns the printed temporary directory for the rest of its CI step.
runtime_ref=${ODOO_IMAGE:?ODOO_IMAGE must be a digest-pinned official image}
subject_digest=${runtime_ref##*@}
raw=$(docker buildx imagetools inspect --raw "$runtime_ref")
manifest_digest=$(printf '%s' "$raw" | jq -r \
  '.manifests[] | select(.platform.os == "linux" and .platform.architecture == "amd64") | .digest' \
  | head -n 1)
config_digest=$(docker buildx imagetools inspect --raw \
  "docker.io/library/odoo@$manifest_digest" | jq -r .config.digest)
test -n "$manifest_digest" && test "$manifest_digest" != null
test -n "$config_digest" && test "$config_digest" != null

docker build --quiet --file deploy/Odoo.Dockerfile \
  --build-arg TARGETARCH=amd64 \
  --build-arg "SOURCE_COMMIT=${GITHUB_SHA:-local}" \
  --build-arg "ODOO_RUNTIME_SOURCE_REF=docker.io/library/odoo@$subject_digest" \
  --build-arg "ODOO_RUNTIME_DEPLOYMENT_REF=docker.io/library/odoo@$subject_digest" \
  --build-arg "ODOO_RUNTIME_SUBJECT_DIGEST=$subject_digest" \
  --build-arg ODOO_RUNTIME_SUBJECT_KIND=image_index \
  --build-arg "ODOO_RUNTIME_MANIFEST_DIGEST=$manifest_digest" \
  --build-arg "ODOO_RUNTIME_CONFIG_DIGEST=$config_digest" \
  --tag mb-odoo-extension:ci . >&2

target=$(mktemp -d)
container=$(docker create mb-odoo-extension:ci)
trap 'docker rm -f "$container" >/dev/null 2>&1 || true' EXIT
docker cp "$container:/payload/." "$target"
test -s "$target/manifest.json"
printf '%s\n' "$target"
