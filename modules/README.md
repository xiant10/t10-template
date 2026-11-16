# modules/

One folder per business module this project runs, `modules/<id>/`, named for its `MODULE_ID`:
its deployment. Its code is in `../src/<service>/`. The template ships none.
`make new-module ID=<id> SERVICE=<service> PORT=<port>` makes both, and the module runs with the
next `make up`. What a module provides, what each file is for and how to work on one is in
`../docs/module.md`.
