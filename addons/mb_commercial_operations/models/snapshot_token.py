"""The capability that makes a frozen planning snapshot immutable.

An object identity, not a string: a snapshot and its attachment refuse any
write or unlink unless the context carries this exact object, so the guard
cannot be satisfied by a caller who merely guesses the context key. It lives
in its own module because the snapshot, its attachment and the operation that
creates one all need it, and they are three separate models.
"""

SNAPSHOT_TOKEN = object()
