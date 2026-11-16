# modules/

One folder per business module this project runs, `modules/<id>/`, named for its `MODULE_ID`.
The template ships none. `make new-module ID=<id> SERVICE=<service> PORT=<port>` makes one, and
it joins the stack once `make sync-module MODULE=<id>` copies its pack out of its image. What a
module provides and what each file in its folder is for is in `../docs/module.md`.
