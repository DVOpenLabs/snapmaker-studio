# Recovery preview identity and freshness

Only a successful current preview enables workspace or sample checkpoint saves.
During a read or after failure, earlier data is collapsed under an explicit
not-current label. A historical preview can still be inspected deliberately;
it is not evidence of current file identity or printer state. The checkpoint's
workspace name is shown separately from the current open job.

Save notices name the project captured by the request. A project switch while
the request is pending cannot relabel it as the new project. A successful save
with an unconfirmed refresh is reported as saved, with a refresh warning; it is
not reported as failed or verified. Backend revision/CAS and the subscriber's
latest-request-wins logic are unchanged. No recovery action replays a print.
