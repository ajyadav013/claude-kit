# pybug

Stock-keeping helpers for a warehouse service.

## Reorder policy

An item needs restocking once its stock has fallen **to** its reorder threshold or below it.
When it does, enough units are ordered to bring stock up to `threshold * 3`.
