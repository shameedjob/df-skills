---
name: df-designer-preview
description: "Renders a DataFlex web view .wo in the DataFlex WebApp designer so its layout can be reviewed without the DataFlex client or running the application. Use when the user asks to preview or review the design of a web view, or to (re)build the design previewer."
---

Use this skill to review the design of a web view without interacting with the DataFlex client: the view's source is turned into a static page that the user opens in a browser. When the preview is generated, finish by reporting the link to the new page (see [Report the link](#report-the-link)). If any step fails, tell the user instead (see [When the skill fails](#when-the-skill-fails)).

The previewer is a copy of the DataFlex `WebUI_Designer` folder kept in a cache folder (the "bundle"). Use the same bundle for every view preview. Once built, each preview overwrites `WebAppDesigner.html` and refreshes `system.css`, `application.css`, and `theme.css` in the bundle root; do not create a separate cache or bundle for each view. If an existing preview bundle is already in use, keep its `DF_SKILLS_CACHE` setting for `status` and `preview`. The bundled class defaults come from a DataFlex Web UI 1.0.52 designer export; use `-b` with a designer export when working with another version or custom JavaScript classes.

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

This replaces the bundle with a fresh copy of `<AppHtml>/WebUI_Designer`, copies `system.css`, `application.css`, and `theme.css` directly into the bundle root, and saves all the paths. The generated HTML links to those three files in that order. Any path left out is taken from the saved config, so a rebuild with unchanged paths is just `bundle`; giving `-I` replaces the whole saved list of search folders. The command prints the bundle folder.

## Preview a view

```
  python scripts/build_designer.py preview -f VIEW_FILE [-b BASE_JSON] [-c CONSTANTS_JSON] [-j OUTPUT_JSON]
```

This refreshes all three root-level CSS files, then overwrites the same bundle's `WebAppDesigner.html` with the requested view and prints a `file:///` browser address for that page. The previous view preview at that address is replaced. When `WebApp.src` sits beside the view, its `oWebApp` settings are included.

Used files are searched for in the view's own folder, the saved search folders, and `AppSrc` folders from file-based dependencies in the view workspace's `.sws` file. If a web class still cannot be traced, check the saved folders with `status` and the workspace dependencies.

- `-I` (repeatable): an extra folder to search in this run only; it is not saved.
- `-b`: an existing designer output JSON that supplies `oWebApp` settings, class defaults, and node handles for matching object paths. Without it, the script uses `res/webapp.json` and `res/designer-classes-1.0.52.json` and generates unique node handles.
- `-c`: a JSON file mapping DataFlex constants to their values, e.g. `{"prLeft": "1"}`. Common layout constants are built in; other unmapped constants are written out by name.
- `-j`: also save the generated designer definition to a JSON file for comparison or debugging.

The standalone page calls the designer only after its body and `#viewport` exist, matching Studio's post-message timing. Class defaults come from the framework source and the DataFlex 1.0.52 designer class catalog; custom JavaScript classes without application scripts use their standard DataFlex parent for layout. When checking a preview in a browser, verify that `#viewport` contains the requested view's `data-dfobj` and controls after the page loads. If browser access to local files is unavailable, inspect the generated page, assets, and designer definition statically, and state that the rendered DOM was not verified.

`preview` exits with an error if the bundle has not been built; build it first as above.

`bundle` also accepts the `preview` options `-f`, `-b`, and `-c` to build and preview in one call.

## Report the link

Once `preview` (or `bundle -f ...`) succeeds, the last line it prints is the browser address of the generated page, e.g.

```
file:///Users/me/.cache/df-skills/designer-preview/bundle/WebAppDesigner.html
```

For the Codex in-app browser, open the generated `file:///` address with the browser-panel tool when it accepts local files. Also report the generated file as a clickable Markdown link using its absolute filesystem path. If opening the panel fails, report that result accurately and still provide the clickable file link. Only give a link when the command succeeded.

## When the skill fails

A command has failed when it exits with a non-zero code, prints a line starting with `error:`, or prints a Python traceback. When previewing a view, that means:

1. Stop. Do not give the user a preview link, even one from an earlier run: the page in the bundle is out of date or missing.
2. Tell the user that the preview could not be generated, which command failed, and the error message as printed.
3. Say what is most likely wrong and what would fix it, using the table below. If the fix needs a path, ask the user for it rather than guessing.
4. Do not work around the failure by editing the bundle, writing the HTML or JSON by hand, or changing the saved config without the user's say.

If the user explicitly asks to repair or develop the preview skill, diagnose the failure and update the skill itself, then rerun the command.

| Error | Likely cause | Fix |
| --- | --- | --- |
| `missing paths ... : <keys>` | `bundle` was run without those paths and they are not saved yet | Ask the user for the listed paths and rerun `bundle` with them |
| `theme.css not found`, `application.css not found` | The saved CSS path moved or was mistyped | Ask the user for the current path and rerun `bundle --theme ...` / `--application-css ...` |
| `WebUI_Designer folder not found`, `system.css not found` | `--apphtml` does not point at the DataFlex `AppHtml` folder | Ask the user for the `AppHtml` folder and rerun `bundle --apphtml ...` |
| `search folder not found` | A folder given with `-I` does not exist | Ask the user for the correct folder and rerun `bundle -I ...` with every search folder |
| `no preview bundle ... run the bundle command first` | The bundle was never built, or its config is from an older version | Run `status`, ask for any missing paths, and run `bundle` |
| `no web objects found in <file>` | The view's classes could not be traced to `cWebObject`, usually because the DataFlex `Pkg` folder or a workspace source folder is not among the search folders | Show the user the search folders from the message, ask which folder is missing, and rerun `bundle -I ...` with the full list |
| `No such file or directory: <view file>` | The view path is wrong | Confirm the view file with the user |
| A Python traceback | A bug in the script, or source it cannot parse | Report the last lines of the traceback and the view file; do not retry with guessed changes |

A preview can also succeed but look wrong, for example missing controls or showing constant names such as `prLeft` where numbers are expected. If the user reports this, or the command output suggests it, say what is missing and point to the likely cause: a class whose file is not in the search folders, or a constant that needs a `-c` constants file.

## Cache location

- macOS / Linux: `.cache/df-skills/designer-preview` (or under `$XDG_CACHE_HOME`)
- Windows: `.cache\df-skills\designer-preview`
- Set `DF_SKILLS_CACHE` only when selecting an existing shared bundle or establishing its stable cache folder. Reuse that value on subsequent previews; do not change it merely to keep an earlier view preview.

The cache also holds `class-inheritance.json`: a reusable mapping from class name to `[parent class, source file]`. Each run checks source file size and modification time and reparses only changed package files and the requested view. Keep this file when replacing a preview or rebuilding the bundle; deleting it makes the next class lookup slower.
