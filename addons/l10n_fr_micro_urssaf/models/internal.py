"""Private capability used for module-owned declaration mutations.

An object-identity check is deliberate: JSON-RPC/import callers can forge context
strings and booleans, but cannot manufacture this in-process object.
"""

INTERNAL_CONTEXT_KEY = "_l10n_fr_micro_urssaf_internal"
INTERNAL_CAPABILITY = object()


def is_internal(env):
	return env.context.get(INTERNAL_CONTEXT_KEY) is INTERNAL_CAPABILITY


def internal_context():
	return {INTERNAL_CONTEXT_KEY: INTERNAL_CAPABILITY}
