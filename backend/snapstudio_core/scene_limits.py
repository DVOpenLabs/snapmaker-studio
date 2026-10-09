"""Every numeric budget, cap, deadline and TTL behind the scene/1 contract, in one place.

Nothing else in the scene code carries a literal limit. These are PROVISIONAL budgets (see
docs/testing/scene-contract/README.md for the corpus they were measured against). Each one is
enforced while the work happens, never after, and exceeding one is a clear LIMIT_EXCEEDED, never
a silently shortened scene.
"""
from __future__ import annotations

MIB = 1024 * 1024

# --- what the engine will copy and read -------------------------------------
SNAPSHOT_MAX_BYTES = 128 * MIB          # hard ceiling on the private copy of the source file
SNAPSHOT_CHUNK_BYTES = 1 * MIB          # streamed copy / archive read unit (bounded uninterruptible work)
DISK_HEADROOM_BYTES = 64 * MIB          # free space required beyond the source size
ARCHIVE_EXPANSION_BYTES = 128 * MIB     # total decompressed bytes the reader will pull from one archive
MODEL_XML_BYTES = 32 * MIB              # decompressed bytes of all .model parts together
CONFIG_PART_BYTES = 8 * MIB             # one metadata/config part (model_settings, Slic3r_PE_model, .rels)
ARCHIVE_MAX_ENTRIES = 20_000            # zip directory entries
MAX_MODEL_PARTS = 256                   # distinct .model files parsed for one scene
MAX_RELS_PARTS = 64                     # .rels parts examined

# --- what the scene may contain ---------------------------------------------
MAX_RENDERED_TRIANGLES = 250_000        # counting every repetition of an instanced mesh
MAX_PARSED_TRIANGLES = 250_000          # distinct triangles accepted while parsing
MAX_VERTICES = 300_000                  # distinct decoded vertices
MAX_NODES = 2_000
MAX_OBJECT_DEFINITIONS = 20_000        # <object> elements across all model parts (10x the node budget)
MAX_XML_ELEMENTS = 1_000_000           # every completed XML element, counted while parsing
MAX_PART_NAME_LENGTH = 256             # archive part names carried on nodes/meshes/sources (schema maxLength)
MAX_DEPTH = 64
MAX_ID_LENGTH = 128
MAX_FINDINGS = 500
MAX_LIMITATIONS = 50
MAX_VOLUMES_PER_MESH = 4_096
MAX_RESPONSE_BYTES = 8 * MIB            # the whole serialized body
MAX_COORDINATE_MM = 1.0e7               # keeps every coordinate representable as float32

# --- cooperative interruption (v4 item 2) -----------------------------------
XML_EVENTS_PER_CHECK = 1_000            # lxml iterparse events between cancel/deadline checks
GEOMETRY_BATCH_TRIANGLES = 5_000        # decode/encode batch; 5_000 * 12 bytes is a multiple of 3 (base64-safe)
VERTEX_BATCH = 15_000                   # transformed vertices between checks

# --- jobs -------------------------------------------------------------------
JOB_DEADLINE_SECONDS = 60.0             # wall clock from the moment the job becomes running
WEDGE_GRACE_SECONDS = 5.0               # worker still alive this long after cancel/TIMEOUT => WORKER_WEDGED
RESULT_TTL_SECONDS = 120.0              # a terminal job is kept this long
MAX_TERMINAL_JOBS = 8                   # ... or until more than this many terminal jobs exist
MAX_REQUEST_ID_LENGTH = 64
MAX_SESSIONS = 32                       # open scene sessions (an idle-expired one that owns no job is pruned first)
SESSION_TTL_SECONDS = 15 * 60           # idle time after which a session without a registered job is pruned
SNAPSHOT_DIR_MIN_AGE_SECONDS = 600     # a dead engine's scene-tmp folder is swept only once it is this old (a live engine's NEVER is)
MAX_PENDING_UNLINKS = 1024             # snapshot files that could not be deleted yet and are retried with back-off

LIMITS_ECHO = {
    "max_archive_bytes": ARCHIVE_EXPANSION_BYTES,
    "max_model_xml_bytes": MODEL_XML_BYTES,
    "max_rendered_triangles": MAX_RENDERED_TRIANGLES,
    "max_vertices": MAX_VERTICES,
    "max_nodes": MAX_NODES,
    "max_depth": MAX_DEPTH,
    "max_response_bytes": MAX_RESPONSE_BYTES,
    "max_findings": MAX_FINDINGS,
    "max_limitations": MAX_LIMITATIONS,
    "max_id_length": MAX_ID_LENGTH,
}
