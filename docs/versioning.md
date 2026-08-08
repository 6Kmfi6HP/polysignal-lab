# Versioning and image channels

`pyproject.toml` is the canonical application version source. It must contain a
stable `X.Y.Z` SemVer value. Branch builds do not edit that value; build
identity is derived by GitHub Actions and stored in OCI labels.

## Image channels

| Source | Source-addressed tag | Moving tag | Build version example |
| --- | --- | --- | --- |
| `debug/orderbook-recovery` | `sha-<full-commit>` | `debug-orderbook-recovery-<branch-id>` | `1.0.0-debug.184+abcdef123456` |
| `main` | `sha-<full-commit>` | `main` | `1.0.0-main.185+abcdef123456` |
| Git tag `v1.0.0` | existing image digest | `1.0.0`, `1.0`, `stable` | unchanged candidate image |

The registry digest is the immutable deployment identity. The `sha-*` tag
records source identity, while `main`, `debug-*`, minor-version, and `stable`
tags are movable channels. Do not use `latest`.

Pushes to `main` and `debug/**` run the complete test and frontend gates before
publishing images. Other branches and pull requests run validation but do not
receive image publishing permissions.

## Debug builds

Create a branch under `debug/` and push it normally. The CI run publishes both
the source-addressed tag and a branch channel tag. The branch channel includes
a stable eight-character branch identifier so similarly normalized branch
names cannot collide.

For repeatable debugging, deploy the `sha-*` tag or the resolved digest rather
than the moving `debug-*` tag. Debug promotion does not create a pull request;
integration into `main` remains an explicit user-controlled Git operation.

## Stable releases

Before creating `vX.Y.Z`, set `project.version` in `pyproject.toml` to the same
`X.Y.Z` value and let the target commit pass the `main` CI image build. Pushing
the tag starts `.github/workflows/release.yml`.

The release workflow fails closed unless all of the following are true:

- the Git tag exactly matches `project.version`;
- the tagged commit is contained in `main`;
- the `sha-*` candidate exists and identifies the tagged commit;
- the candidate was built through the `main` channel;
- its GitHub Actions provenance is valid and signed by `ci.yml`;
- an existing exact version tag does not point to another digest.

The workflow does not rebuild. It promotes the verified digest to the exact
version, major/minor, and `stable` tags, then records that digest in a GitHub
Release.

## Compose deployment

Both backend services use the same full image reference:

```bash
# Moving integration channel
POLYSIGNAL_IMAGE_REF=ghcr.io/6kmfi6hp/polysignal-lab:main docker compose up -d

# Branch debug channel
POLYSIGNAL_IMAGE_REF=ghcr.io/6kmfi6hp/polysignal-lab:debug-orderbook-recovery-<branch-id> docker compose up -d

# Reproducible source build
POLYSIGNAL_IMAGE_REF=ghcr.io/6kmfi6hp/polysignal-lab:sha-<full-commit> docker compose up -d

# Production pin
POLYSIGNAL_IMAGE_REF=ghcr.io/6kmfi6hp/polysignal-lab@sha256:<digest> docker compose up -d
```

Production should use the digest form. Changing a channel tag alone must never
be treated as proof that a running container was recreated or upgraded.

## Nautilus dependency version

The NautilusTrader wheel has an independent immutable release identity. An
application image must continue to record its exact Nautilus source commit,
release tag, and wheel SHA256 in the canonical manifest and OCI labels. Normal
application debug branches use the currently pinned wheel; a candidate fork
wheel must not overwrite the production manifest or stable image tags.
