import re


class SnapStudioError(Exception): ...
class PartNotFound(SnapStudioError): ...
class PreservationError(SnapStudioError): ...
class FilamentLimitError(SnapStudioError): ...


# `object 4 ("Lid"): skin_infill_density is not a setting Studio has proved ...`
_UNVERIFIED = re.compile(
    r'^object (?P<id>\S+?)(?: \("(?P<name>[^"]*)"\))?: (?P<key>[A-Za-z0-9_]+) is not a setting '
    r"Studio has proved")
_NIL_PART = re.compile(
    r'^part (?P<part>\S+) of object (?P<id>\S+?)(?: \("(?P<name>[^"]*)"\))?: has values '
    r"Snapmaker Orca 2.4.0 cannot read \(nil in (?P<keys>[^)]*)\)")
_BAD_VALUE = re.compile(
    r'^object (?P<id>\S+?)(?: \("(?P<name>[^"]*)"\))?: (?P<key>[A-Za-z0-9_]+)=')


def _who(object_id: str, name: str | None) -> str:
    return f'object {object_id} ("{name}")' if name else f"object {object_id}"


def plain_refusal(problems: list[str]) -> str:
    """The refusal as a person reads it: which settings or structure, and what to do.

    Only describes next steps that exist today: reviewing the original in
    Snapmaker Orca, or removing the setting in the slicer that made the file and
    exporting it again. The raw wording stays in `UnsoundOutput.details`.
    """
    unverified: dict[str, list[str]] = {}
    bad_values: list[str] = []
    other = 0
    nil_parts: list[str] = []
    for problem in problems:
        m = _NIL_PART.match(problem)
        if m:
            nil_parts.append(f"part {m['part']} of {_who(m['id'], m['name'])} ({m['keys']})")
            continue
        m = _UNVERIFIED.match(problem)
        if m:
            unverified.setdefault(_who(m["id"], m["name"]), []).append(m["key"])
            continue
        m = _BAD_VALUE.match(problem)
        if m:
            bad_values.append(f'{m["key"]} on {_who(m["id"], m["name"])}')
            continue
        other += 1
    parts: list[str] = []
    if nil_parts:
        parts.append(
            "Snapmaker Orca 2.4.0 cannot load this project: "
            + "; ".join(nil_parts)
            + " has values it cannot read (a blank 'nil' entry), and Orca stops "
              "loading the whole file when it meets one. Studio does not edit those "
              "values for you. Open the original in the slicer that made it, reset those "
              "part settings, and export it again.")
    if unverified:
        total = sum(len(keys) for keys in unverified.values())
        where = "; ".join(f"on {who}: {', '.join(sorted(set(keys)))}"
                          for who, keys in unverified.items())
        parts.append(
            "Studio only keeps per-object settings it has verified Snapmaker Orca reads. "
            f"{total} setting(s) are not verified, {where}. Open the original in "
            "Snapmaker Orca to review those settings, or remove them in the slicer that "
            "made the file and export it again.")
    if bad_values:
        parts.append(
            "Studio cannot confirm Snapmaker Orca reads the value of "
            + ", ".join(bad_values)
            + ", and a value Orca cannot read can cost the whole object. Check those "
              "values in the original, or remove them and export again.")
    if other:
        parts.append(
            f"The project's internal structure does not agree with itself in {other} "
            "place(s), so Studio cannot vouch for a prepared copy of it. Open the "
            "original in Snapmaker Orca to check that it looks right.")
    if not parts:
        parts.append("Studio could not vouch for a prepared copy of this file.")
    parts.append("No prepared copy was saved, and your original file was not changed.")
    return " ".join(parts)


class UnsoundOutput(SnapStudioError):
    """Studio built a prepared copy whose own descriptions disagree.

    A prepared project states the same structure three times — the root model's
    components, the mesh objects they point at, and the part records in
    `model_settings.config`. If those drift apart the file is wrong even though
    each part of it is well-formed, and Snapmaker Orca should not be the first
    thing to notice. Raised instead of handing over the file; the original is
    untouched either way, because preparing never writes to it.

    `str(exc)` is the plain-language message shown to a person. The raw wording
    stays available as `problems` (a list) and `details` (one string).
    """

    def __init__(self, problems: list[str]) -> None:
        self.problems = list(problems)
        self.details = ("Studio built a prepared copy it cannot vouch for and did not save it: "
                        + "; ".join(self.problems))
        super().__init__(plain_refusal(self.problems))


class UnsafeArchive(SnapStudioError):
    """A 3MF that Studio refuses to open: too many entries, or it decompresses to
    more data than the reader budget allows (a zip bomb, or a corrupt file that
    looks like one). The message is safe to show a user verbatim."""
