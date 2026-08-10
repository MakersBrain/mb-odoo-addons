"""Private capability for module-owned depot report state transitions.

RPC and import callers can forge strings and booleans in a context, but cannot
manufacture this in-process object identity.
"""

INTERNAL_CONTEXT_KEY = "_mb_depot_internal"
INTERNAL_CAPABILITY = object()


def is_internal(env):
    return env.context.get(INTERNAL_CONTEXT_KEY) is INTERNAL_CAPABILITY


def internal_context():
    return {INTERNAL_CONTEXT_KEY: INTERNAL_CAPABILITY}
