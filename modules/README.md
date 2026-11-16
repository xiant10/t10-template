# modules/

One folder per business module this project runs, `modules/<id>/`, named for its `MODULE_ID`:
its deployment, holding only what's particular to it. Its code is in `../src/<id>/`, and how it
plugs into the foundation is the template's, worked out from its pack. The template ships none.
`make new-module ID=<id>` makes both, and the module runs with the next `make up`. What a module
provides, what each file is for and how to work on one is in `../docs/module.md`.
