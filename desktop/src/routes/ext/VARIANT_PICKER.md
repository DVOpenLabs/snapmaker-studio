# Variants native file-picker ordering

The latest requested dialog and the current input revision must still match
before a native picker path/error may update the comparison. Manual edits,
another dialog or page unmount invalidate the earlier answer. Cancelling a
dialog keeps existing paths. No picker action starts comparison or opens a file
in another application. Tested with deferred native-dialog stand-ins; live OS
dialog behavior is not claimed. Comparison parsing and job association unchanged.
