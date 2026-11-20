# Saved assembly list failure recovery

The initial list request and explicit Refresh saved assemblies share a latest-
request guard. A failed list read is visible, retains the editor and any earlier
list with an out-of-date warning, and can be retried without leaving the page.
Saving uses a new list request, invalidating any older mount-time list reply.
Failure to refresh after a successful save does not misreport the save as failed.
Refreshing never opens an assembly, changes its revision, or evaluates spools.
Unmount invalidates pending list replies. There is no background retry loop.
