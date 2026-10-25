# Model intake resource limits

Print Buddy refuses oversized sources before loading full XML trees or mesh arrays.
A compressed 3MF can expand far beyond its upload size, so a small download alone
is not evidence that the geometry is safe to inspect.

Limits in this revision:

| Resource | Limit |
| --- | --- |
| Download or local source | 200 MiB |
| ZIP members | 4,096 |
| Total expanded ZIP content | 256 MiB |
| Any expanded ZIP member | 64 MiB |
| Aggregate `.model` XML | 32 MiB |
| STL file | 32 MiB |
| XML triangles / vertices | 500,000 each |
| XML elements across models | 1,100,000 |

ZIP sizes are checked before opening any member. Accepted model XML is then
counted with a streaming parser, not a DOM. XML document type declarations are
refused. Binary STL triangle counts are checked from the header when its length
matches the file. The STL byte limit also applies to ASCII STL. Site downloads
count actual streamed bytes even if Content-Length is missing or incorrect;
failed partial downloads are removed.

Discord upload, link and reprint intake check before title extraction, audit and
color prompts. Direct audit, color inventory and geometry loading apply the same
guard. A refusal explains which budget was exceeded and asks you to simplify the
mesh or split it into smaller files in your modeling app. Nothing is sliced or
started for a refused intake.

These conservative limits can reject otherwise valid large projects. They are
not configurable bypasses and do not guarantee a particular RSS for all accepted
models: repeated component instances and downstream slicer allocations vary.
This is not a general sandbox or a replacement for printer safety checks.

[Documentation home](README.md)
