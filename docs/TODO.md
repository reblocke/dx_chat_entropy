# TODO

## Differential LR Pipeline

- [ ] Add master-workbook Excel I/O mode for differential LR generation.
  - Current behavior writes many per-pair workbooks with one result column each.
  - Target behavior should support a single master workbook with sheet-based scenario organization and grid-style columns.
  - Input formatting task:
    - define a canonical column layout for a scenario sheet (findings as rows, comparator/pair headers as columns),
    - support reading this layout directly instead of requiring many per-pair files.
  - Output formatting task:
    - write one master output workbook per model with one sheet per scenario,
    - include all pairwise differential LR values in a grid (not one column per file),
    - include clear comparator labels and stable column ordering.
  - Keep current per-pair workflow available until master-workbook mode is validated.
