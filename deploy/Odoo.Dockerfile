# syntax=docker/dockerfile:1.7

# The official runtime is used only as a qualification/build environment. It is
# not the final image and is never modified for deployment.
FROM odoo:19@sha256:94a4f480b8039dc9ca2bca9e77e59f97d3311f66e2aad663cf2670be9c66d4ea AS payload
USER root
ARG TARGETOS=linux
ARG TARGETARCH
ARG TARGETVARIANT=""
ARG SOURCE_COMMIT=""
ARG ODOO_RUNTIME_SOURCE_REF
ARG ODOO_RUNTIME_DEPLOYMENT_REF
ARG ODOO_RUNTIME_SUBJECT_DIGEST
ARG ODOO_RUNTIME_SUBJECT_KIND=image_index
ARG ODOO_RUNTIME_MANIFEST_DIGEST
ARG ODOO_RUNTIME_CONFIG_DIGEST
COPY addons /src/addons
COPY contracts /src/contracts
COPY dependencies /src/dependencies
COPY tools/dependency_policy.py tools/extension_manifest.py /src/tools/
RUN mkdir -p /payload/python \
 && cp -a /src/addons /payload/addons \
 && cd /src \
 && python3 tools/dependency_policy.py --build /payload/python \
 && chmod -R u=rwX,go=rX /payload \
 && python3 tools/extension_manifest.py \
      --payload /payload \
      --runtime-source-ref "$ODOO_RUNTIME_SOURCE_REF" \
      --runtime-deployment-ref "$ODOO_RUNTIME_DEPLOYMENT_REF" \
      --runtime-subject-digest "$ODOO_RUNTIME_SUBJECT_DIGEST" \
      --runtime-subject-kind "$ODOO_RUNTIME_SUBJECT_KIND" \
      --runtime-manifest-digest "$ODOO_RUNTIME_MANIFEST_DIGEST" \
      --runtime-config-digest "$ODOO_RUNTIME_CONFIG_DIGEST" \
      --os "$TARGETOS" --architecture "$TARGETARCH" --variant "$TARGETVARIANT" \
      --source-commit "$SOURCE_COMMIT"

# An inert, executable-free transport image. Deployment copies /payload with
# its trusted helper and never starts a container from this image.
FROM scratch
COPY --from=payload --chown=65532:65532 /payload /payload
USER 65532:65532
ENTRYPOINT []
CMD ["/mb-extension-transport-is-not-executable"]

ARG SOURCE_COMMIT=""
ARG SOURCE_REF=""
LABEL org.opencontainers.image.source="https://github.com/MakersBrain/mb-odoo-addons" \
      org.opencontainers.image.revision="${SOURCE_COMMIT}" \
      org.opencontainers.image.version="${SOURCE_REF}" \
      org.opencontainers.image.title="mb-odoo-extension" \
      org.opencontainers.image.description="Immutable MakersBrain addon extension bundle for official Odoo 19" \
      org.opencontainers.image.licenses="AGPL-3.0-only"
