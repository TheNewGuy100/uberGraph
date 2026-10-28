// Syntax check for the mod's Lua files (UE4SS runs Lua 5.4; luaparse understands 5.3, enough for the syntax used here).
// Usage, from the repository root:
//     cd tools/lua-check && npm install && cd ../.. && node tools/lua-check/check-lua.js [file.lua ...]
// With no arguments it checks every .lua under mods/. Exit code 1 if any file fails. It does not run the code.
const fs = require("fs");
const path = require("path");
const luaparse = require("luaparse");

const root = path.resolve(__dirname, "..", "..");

function collect(dir, found) {
    for (const entry of fs.readdirSync(dir, {withFileTypes: true})) {
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) collect(full, found);
        else if (entry.name.endsWith(".lua")) found.push(full);
    }
    return found;
}

const files = process.argv.length > 2
    ? process.argv.slice(2).map((f) => path.resolve(f))
    : collect(path.join(root, "mods"), []);

let failed = 0;
for (const file of files) {
    try {
        const ast = luaparse.parse(fs.readFileSync(file, "utf8"), {luaVersion: "5.3"});
        // Lua allows at most 200 active local variables per function; the main chunk of main.lua once hit that and the mod
        // failed to load. Count the locals declared directly in the chunk and warn well before the limit.
        let locals = 0;
        for (const statement of ast.body) {
            if (statement.type === "LocalStatement") locals += statement.variables.length;
            else if (statement.type === "FunctionDeclaration" && statement.isLocal) locals += 1;
        }
        const note = locals >= 190 ? "  LIMITE DE LOCAIS PERTO (" + locals + "/200)" : locals >= 170 ? "  aviso: " + locals + "/200 locais no chunk principal" : "";
        if (locals >= 190) failed++;
        console.log((locals >= 190 ? "ERRO   " : "ok     ") + path.relative(root, file) + note);
    } catch (error) {
        failed++;
        console.log("ERRO   " + path.relative(root, file) + ": " + error.message);
    }
}
process.exit(failed ? 1 : 0);
