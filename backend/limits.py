"""Size limits on what the app hands the narrator, in one place.

The narrator's harness shows a tool result whole only up to
`TOOL_RESULT_LIMIT` characters. Past that it writes the result to a file and
shows the narrator a preview, so anything the narrator must read whole has to
land well short of it. Every read the app builds for the narrator is held under
`READ_CEILING`, which leaves room for the result envelope and a margin.
"""

from __future__ import annotations

#: The harness's tool-result limit, in characters of the result text.
TOOL_RESULT_LIMIT = 30_000

#: The size the app holds a narrator read under, in characters.
READ_CEILING = 26_000
