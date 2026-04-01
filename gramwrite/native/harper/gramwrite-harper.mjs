import process from "node:process";

const ACTION_LINE_PREFIX = /^\[ACTION LINE[^\n]*\]\n/;

function writeJson(payload) {
    process.stdout.write(JSON.stringify(payload));
}

function formatError(error) {
    if (error instanceof Error) {
        return error.message;
    }
    return String(error);
}

function installHint() {
    return "Run npm install in gramwrite/native/harper to enable the Harper backend.";
}

async function loadHarper() {
    try {
        return await import("harper.js");
    } catch (error) {
        throw new Error(`${formatError(error)} ${installHint()}`.trim());
    }
}

async function createLinter() {
    const harper = await loadHarper();
    const dialect = harper.Dialect?.American ?? harper.Dialect?.British;
    const linter = new harper.LocalLinter({
        binary: harper.binary,
        ...(dialect ? { dialect } : {}),
    });
    if (typeof linter.setup === "function") {
        await linter.setup();
    }
    return linter;
}

async function readJsonStdin() {
    const chunks = [];
    for await (const chunk of process.stdin) {
        chunks.push(chunk);
    }
    const raw = Buffer.concat(chunks).toString("utf-8").trim();
    return raw ? JSON.parse(raw) : {};
}

async function reportStatus() {
    try {
        const linter = await createLinter();
        await linter.lint("This are a test sentence.");
        if (typeof linter.dispose === "function") {
            await linter.dispose();
        }
        writeJson({
            supported: true,
            available: true,
            reason: null,
        });
    } catch (error) {
        writeJson({
            supported: true,
            available: false,
            reason: formatError(error),
        });
    }
}

async function applyCorrections(linter, text) {
    let current = text;

    for (let attempt = 0; attempt < 8; attempt += 1) {
        const lints = await linter.lint(current);
        const actionable = lints.filter(
            (lint) =>
                typeof lint.suggestion_count === "function" &&
                lint.suggestion_count() > 0 &&
                typeof lint.suggestions === "function" &&
                lint.suggestions().length > 0,
        );

        if (actionable.length === 0) {
            return current;
        }

        let changed = false;
        for (const lint of actionable) {
            const [firstSuggestion] = lint.suggestions();
            if (!firstSuggestion) {
                continue;
            }
            const next = await linter.applySuggestion(current, lint, firstSuggestion);
            if (typeof next === "string" && next !== current) {
                current = next;
                changed = true;
                break;
            }
        }

        if (!changed) {
            return current;
        }
    }

    return current;
}

async function correctText() {
    try {
        const request = await readJsonStdin();
        const source = String(request.text ?? "").replace(ACTION_LINE_PREFIX, "");

        if (!source.trim()) {
            writeJson({
                ok: true,
                hasCorrection: false,
            });
            return;
        }

        const linter = await createLinter();
        const correction = await applyCorrections(linter, source);
        if (typeof linter.dispose === "function") {
            await linter.dispose();
        }

        writeJson({
            ok: true,
            hasCorrection: correction !== source,
            correction,
        });
    } catch (error) {
        writeJson({
            ok: false,
            error: formatError(error),
        });
        process.exitCode = 1;
    }
}

const command = process.argv[2] ?? "status";

if (command === "status") {
    await reportStatus();
} else if (command === "correct") {
    await correctText();
} else {
    writeJson({
        ok: false,
        error: `Unknown Harper helper command: ${command}`,
    });
    process.exitCode = 1;
}
