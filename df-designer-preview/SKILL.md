---
name: df-designer-preview
description: "Renders a DataFlex web view (.wo/.vw) in the DataFlex WebApp designer so its layout can be reviewed without running the application. Use when the user asks to preview or review the design of a web view, or to (re)build the design previewer."
---

The previewer is a copy of the DataFlex `WebUI_Designer` folder kept in a cache folder (the "bundle"). It is built once, and each view review then regenerates only the page and the application's CSS inside it.

All commands are run as `python scripts/build_designer.py <command> ...`.

## Check the setup first

```
  python scripts/build_designer.py status
```

Prints the cache folder, whether the bundle is built (`bundle_built`), and the paths saved in its config.

## Build the bundle: first use, or when the user asks to rebuild the previewer

Only do this when `bundle_built` is `false`, or when the user asks to rebuild the design previewer. If the config is missing any of these paths, ask the user for them:

- the application's `theme.css`
- the application's `application.css`
- the DataFlex `AppHtml` folder (the one containing `WebUI_Designer` and `WebUI/system.css`)
- the folders to search for the files a view `Use`s: the workspace's source folders (e.g. `AppSrc`) and the DataFlex install's `Pkg` folder

```
  python scripts/build_designer.py bundle --theme THEME_CSS --application-css APPLICATION_CSS --apphtml APPHTML_DIR -I APP_SRC -I DATAFLEX_PKG
```

This replaces the bundle with a fresh copy of `<AppHtml>/WebUI_Designer`, adds `theme.css`, `application.css`, and `<AppHtml>/WebUI/system.css`, and saves all the paths. Any path left out is taken from the saved config, so a rebuild with unchanged paths is just `bundle`; giving `-I` replaces the whole saved list of search folders. The command prints the bundle folder.

## Preview a view

```
  python scripts/build_designer.py preview -f VIEW_FILE [-b BASE_JSON] [-c CONSTANTS_JSON]
```

This copies the current `theme.css` and `application.css` into the bundle again, then writes the view's preview as the bundle's `WebAppDesigner.html` and prints that page's path. Give that path to the user to open in a browser.

Used files are searched for in the view's own folder and the saved search folders. If the web classes cannot be found there, the preview will be empty: check the saved folders with `status`.

- `-I` (repeatable): an extra folder to search in this run only; it is not saved.
- `-b`: an existing designer output JSON whose `oWebApp` object and `df.WebApp` class are kept as they are.
- `-c`: a JSON file mapping DataFlex constants to their values, e.g. `{"prLeft": "1"}`. Unmapped constants are written out by name.

`preview` exits with an error if the bundle has not been built; build it first as above.

`bundle` also accepts the `preview` options `-f`, `-b`, and `-c` to build and preview in one call.

## Cache location

- macOS / Linux: `~/.cache/df-skills/designer-preview` (or under `$XDG_CACHE_HOME`)
- Windows: `%LOCALAPPDATA%\df-skills\designer-preview`
- Set `DF_SKILLS_CACHE` to use another folder.
