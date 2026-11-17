# modules/

One folder per business module this project runs, `modules/<id>/`, named for its `MODULE_ID`:
its deployment and its code (`modules/<id>/src/`). How it plugs into the foundation is the
template's (`../platform/scripts/wiring.py`), worked out from its pack (`modules/<id>/src/module/`).
The template ships none. `make new-module ID=<id>` makes a working one, and the module runs with
the next `make up`. What a module provides, what each file is for and how to work on one is in
`../platform/docs/module.md`.
