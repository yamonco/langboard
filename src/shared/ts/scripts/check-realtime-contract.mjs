import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import ts from "typescript";

const contract = JSON.parse(fs.readFileSync(path.resolve("../realtime/contract.json"), "utf8"));

const readSource = (filename) => ts.createSourceFile(filename, fs.readFileSync(filename, "utf8"), ts.ScriptTarget.Latest, true);

const readEnumValues = (source, enumName) => {
    const declaration = source.statements.find((statement) => ts.isEnumDeclaration(statement) && statement.name.text === enumName);
    assert(declaration, `Missing ${enumName}`);

    return declaration.members.map((member) => {
        assert(member.initializer, `Missing initializer for ${member.name.getText(source)}`);
        if (ts.isStringLiteral(member.initializer)) {
            return member.initializer.text;
        }
        if (ts.isNumericLiteral(member.initializer)) {
            return Number(member.initializer.text);
        }
        throw new Error(`Unsupported initializer for ${member.name.getText(source)}`);
    });
};

const readConstValue = (source, constName) => {
    for (const statement of source.statements) {
        if (!ts.isVariableStatement(statement)) {
            continue;
        }
        const declaration = statement.declarationList.declarations.find(
            (candidate) => ts.isIdentifier(candidate.name) && candidate.name.text === constName
        );
        if (!declaration?.initializer) {
            continue;
        }
        const initializer = ts.isAsExpression(declaration.initializer) ? declaration.initializer.expression : declaration.initializer;
        assert(ts.isStringLiteral(initializer), `${constName} must be a string literal`);
        return initializer.text;
    }
    throw new Error(`Missing ${constName}`);
};

const readNumericConstValue = (source, constName) => {
    for (const statement of source.statements) {
        if (!ts.isVariableStatement(statement)) {
            continue;
        }
        const declaration = statement.declarationList.declarations.find(
            (candidate) => ts.isIdentifier(candidate.name) && candidate.name.text === constName
        );
        if (!declaration?.initializer) {
            continue;
        }
        const initializer = ts.isAsExpression(declaration.initializer) ? declaration.initializer.expression : declaration.initializer;
        assert(ts.isNumericLiteral(initializer), `${constName} must be a numeric literal`);
        return Number(initializer.text);
    }
    throw new Error(`Missing ${constName}`);
};

const sorted = (values) => [...values].sort((left, right) => String(left).localeCompare(String(right)));
const topicSource = readSource("src/enums/ESocketTopic.ts");
const statusSource = readSource("src/enums/ESocketStatus.ts");

assert.deepEqual(sorted(readEnumValues(topicSource, "ESocketTopic")), sorted(Object.values(contract.topics)));
assert.deepEqual(sorted(readEnumValues(topicSource, "ESettingSocketTopicID")), sorted(Object.values(contract.setting_topic_ids)));
assert.deepEqual(sorted(readEnumValues(statusSource, "ESocketStatus")), sorted(Object.values(contract.close_codes)));
assert.equal(readConstValue(topicSource, "GLOBAL_TOPIC_ID"), contract.topic_ids.global);
assert.equal(readConstValue(topicSource, "NONE_TOPIC_ID"), contract.topic_ids.none);
assert.equal(readNumericConstValue(topicSource, "SOCKET_MAX_TOPIC_IDS"), contract.protocol_limits.max_topic_ids);
assert.equal(readNumericConstValue(topicSource, "SOCKET_MAX_TOPIC_ID_BYTES"), contract.protocol_limits.max_topic_id_bytes);
