// After Effects side of the Video Downloader panel. Called from panel.js with
// evalScript; returns "ok:<message>" or "error:<message>".

function vdFolder() {
    for (var i = 1; i <= app.project.numItems; i++) {
        var it = app.project.item(i);
        if (it instanceof FolderItem && it.name === "Video Downloader") return it;
    }
    return app.project.items.addFolder("Video Downloader");
}

function vdImport(path, addToComp) {
    var file = new File(path);
    if (!file.exists) return "error:File not found: " + path;
    app.beginUndoGroup("Import from Video Downloader");
    try {
        var item = app.project.importFile(new ImportOptions(file));
        item.parentFolder = vdFolder();
        var where = "the project";
        var comp = app.project.activeItem;
        if (addToComp && comp instanceof CompItem) {
            comp.layers.add(item);
            where = "“" + comp.name + "”";
        }
        return "ok:Imported " + item.name + " into " + where;
    } catch (e) {
        return "error:" + e.toString();
    } finally {
        app.endUndoGroup();
    }
}
