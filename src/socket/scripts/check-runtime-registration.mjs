import assert from "node:assert/strict";
import { Buffer } from "node:buffer";
import fs from "node:fs";
import path from "node:path";
import ts from "typescript";

const contract = JSON.parse(fs.readFileSync(path.resolve("../shared/realtime/contract.json"), "utf8"));
const parse = (filename) => ts.createSourceFile(filename, fs.readFileSync(filename, "utf8"), ts.ScriptTarget.Latest, true);
const unwrap = (node) => (ts.isAsExpression(node) || ts.isSatisfiesExpression(node) ? unwrap(node.expression) : node);
const sorted = (values) => [...values].sort((left, right) => JSON.stringify(left).localeCompare(JSON.stringify(right)));

const moduleNames = (directory) =>
    fs
        .readdirSync(directory, { withFileTypes: true })
        .filter((entry) => entry.isFile() && entry.name.endsWith(".ts") && entry.name !== "index.ts")
        .map((entry) => path.basename(entry.name, ".ts"))
        .sort();

const collectImports = (...filenames) => {
    const imports = new Set();
    for (const filename of filenames) {
        const source = parse(filename);
        for (const statement of source.statements) {
            if (ts.isImportDeclaration(statement) && ts.isStringLiteral(statement.moduleSpecifier)) {
                imports.add(statement.moduleSpecifier.text);
            }
        }
    }
    return imports;
};

const assertModulesImported = (directory, prefix, imports) => {
    for (const moduleName of moduleNames(directory)) {
        assert(imports.has(`${prefix}/${moduleName}`), `${prefix}/${moduleName} is not loaded by the runtime`);
    }
};

const variableInitializer = (source, variableName) => {
    for (const statement of source.statements) {
        if (!ts.isVariableStatement(statement)) {
            continue;
        }
        const declaration = statement.declarationList.declarations.find(
            (candidate) => ts.isIdentifier(candidate.name) && candidate.name.text === variableName
        );
        if (declaration?.initializer) {
            return unwrap(declaration.initializer);
        }
    }
    throw new Error(`Missing ${variableName} in ${source.fileName}`);
};

const propertyName = (source, property) => {
    assert(property.name, `Missing property name in ${source.fileName}`);
    if (ts.isIdentifier(property.name) || ts.isStringLiteral(property.name)) {
        return property.name.text;
    }
    throw new Error(`Unsupported property name in ${source.fileName}`);
};

const collectObjectStringLeaves = (source, node, prefix, result = new Map()) => {
    node = unwrap(node);
    assert(ts.isObjectLiteralExpression(node), `${prefix} must be an object literal`);

    for (const property of node.properties) {
        assert(ts.isPropertyAssignment(property), `Unsupported ${prefix} property in ${source.fileName}`);
        const key = `${prefix}.${propertyName(source, property)}`;
        const value = unwrap(property.initializer);
        if (ts.isStringLiteral(value)) {
            result.set(key, value.text);
        } else {
            collectObjectStringLeaves(source, value, key, result);
        }
    }
    return result;
};

const readObjectStringLeaves = (filename, variableName, rootName = variableName) => {
    const source = parse(filename);
    return collectObjectStringLeaves(source, variableInitializer(source, variableName), rootName);
};

const readEnumEntries = (filename, enumName) => {
    const source = parse(filename);
    const declaration = source.statements.find((statement) => ts.isEnumDeclaration(statement) && statement.name.text === enumName);
    assert(declaration, `Missing ${enumName}`);

    return new Map(
        declaration.members.map((member) => {
            assert(member.initializer && ts.isStringLiteral(member.initializer), `Invalid ${enumName} member`);
            return [member.name.getText(source), member.initializer.text];
        })
    );
};

const expressionPath = (source, node) => {
    if (ts.isIdentifier(node)) {
        return node.text;
    }
    assert(ts.isPropertyAccessExpression(node), `Unsupported expression in ${source.fileName}`);
    return `${expressionPath(source, node.expression)}.${node.name.text}`;
};

const editorPrefixes = (() => {
    const source = parse("src/events/Editor.ts");
    const initializer = variableInitializer(source, "EDITOR_TYPES");
    assert(ts.isArrayLiteralExpression(initializer), "EDITOR_TYPES must be an array literal");

    return initializer.elements.map((element) => {
        element = unwrap(element);
        assert(ts.isObjectLiteralExpression(element), "EDITOR_TYPES members must be object literals");
        const typeProperty = element.properties.find((property) => ts.isPropertyAssignment(property) && propertyName(source, property) === "type");
        assert(typeProperty && ts.isPropertyAssignment(typeProperty), "EDITOR_TYPES member is missing type");
        const value = unwrap(typeProperty.initializer);
        assert(ts.isStringLiteral(value), "EDITOR_TYPES type must be a string literal");
        return value.text;
    });
})();

const topicEntries = readEnumEntries("../shared/ts/src/enums/ESocketTopic.ts", "ESocketTopic");
const clientEventValues = readObjectStringLeaves("../shared/ts/src/constants/SocketEvents.ts", "CLIENT", "SocketEvents.CLIENT");
const routingValues = readObjectStringLeaves("../shared/ts/src/constants/Routing.ts", "API", "Routing.API");

const resolveEventValues = (source, node) => {
    if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) {
        return [node.text];
    }
    if (ts.isPropertyAccessExpression(node)) {
        const key = expressionPath(source, node);
        const value = clientEventValues.get(key);
        assert(value, `Unknown client event ${key} in ${source.fileName}`);
        return [value];
    }
    if (ts.isTemplateExpression(node)) {
        assert(node.templateSpans.length === 1, `Unsupported event template in ${source.fileName}`);
        const [span] = node.templateSpans;
        assert(
            ts.isIdentifier(span.expression) && span.expression.text === "eventPrefix",
            `Unsupported event template expression in ${source.fileName}`
        );
        return editorPrefixes.map((prefix) => `${node.head.text}${prefix}${span.literal.text}`);
    }
    throw new Error(`Unsupported event registration in ${source.fileName}`);
};

const collectRuntimeRegistrations = (directory, ownerName, methodName, callback) => {
    const registrations = [];
    const visit = (source, node) => {
        if (
            ts.isCallExpression(node) &&
            ts.isPropertyAccessExpression(node.expression) &&
            ts.isIdentifier(node.expression.expression) &&
            node.expression.expression.text === ownerName &&
            node.expression.name.text === methodName
        ) {
            callback(source, node, registrations);
        }
        ts.forEachChild(node, (child) => visit(source, child));
    };

    for (const moduleName of moduleNames(directory)) {
        const source = parse(path.join(directory, `${moduleName}.ts`));
        visit(source, source);
    }
    return registrations;
};

const registeredTopics = collectRuntimeRegistrations("src/validators", "Subscription", "registerValidator", (source, node, registrations) => {
    const topic = node.arguments[0];
    assert(
        topic && ts.isPropertyAccessExpression(topic) && ts.isIdentifier(topic.expression) && topic.expression.text === "ESocketTopic",
        `Invalid topic registration in ${source.fileName}`
    );
    const value = topicEntries.get(topic.name.text);
    assert(value, `Unknown socket topic ${topic.name.text}`);
    registrations.push(value);
});

const clientCommands = collectRuntimeRegistrations("src/events", "EventManager", "on", (source, node, registrations) => {
    const topic = node.arguments[0];
    const event = node.arguments[1];
    assert(
        topic && ts.isPropertyAccessExpression(topic) && ts.isIdentifier(topic.expression) && topic.expression.text === "ESocketTopic",
        `Invalid command topic in ${source.fileName}`
    );
    assert(event, `Missing command event in ${source.fileName}`);
    const topicValue = topicEntries.get(topic.name.text);
    assert(topicValue, `Unknown command topic ${topic.name.text}`);
    for (const eventValue of resolveEventValues(source, event)) {
        registrations.push({ topic: topicValue, event: eventValue });
    }
});

const resolveRoutePath = (source, node) => {
    if (ts.isStringLiteral(node)) {
        return node.text;
    }
    if (ts.isPropertyAccessExpression(node)) {
        const key = expressionPath(source, node);
        const value = routingValues.get(key);
        assert(value, `Unknown route ${key} in ${source.fileName}`);
        return value;
    }
    if (ts.isIdentifier(node) && node.text === "path") {
        return null;
    }
    throw new Error(`Unsupported route registration in ${source.fileName}`);
};

const httpRoutes = [];
for (const moduleName of moduleNames("src/routes")) {
    const source = parse(path.join("src/routes", `${moduleName}.ts`));
    const visit = (node) => {
        if (ts.isCallExpression(node)) {
            if (
                ts.isPropertyAccessExpression(node.expression) &&
                ts.isIdentifier(node.expression.expression) &&
                node.expression.expression.text === "Routes" &&
                ["get", "post"].includes(node.expression.name.text)
            ) {
                const routePath = resolveRoutePath(source, node.arguments[0]);
                if (routePath) {
                    httpRoutes.push({ method: node.expression.name.text.toUpperCase(), path: routePath });
                }
            } else if (ts.isIdentifier(node.expression) && node.expression.text === "registerEditorSyncRoute") {
                const routePath = resolveRoutePath(source, node.arguments[0]);
                assert(routePath, `Missing editor sync route in ${source.fileName}`);
                httpRoutes.push({ method: "POST", path: routePath });
            }
        }
        ts.forEachChild(node, visit);
    };
    visit(source);
}

const brokerConsumers = collectRuntimeRegistrations("src/consumers", "Consumer", "register", (source, node, registrations) => {
    const event = node.arguments[0];
    const purpose = node.arguments[2];
    assert(event && ts.isStringLiteral(event), `Invalid broker registration in ${source.fileName}`);
    assert(purpose && ts.isStringLiteral(purpose), `Missing broker purpose in ${source.fileName}`);
    registrations.push({ event: event.text, purpose: purpose.text });
});

const hocusSource = parse("src/core/server/Hocus.ts");
const editorLifecycleHooks = [];
const visitHocus = (node) => {
    if (
        ts.isNewExpression(node) &&
        ts.isIdentifier(node.expression) &&
        node.expression.text === "Hocuspocus" &&
        node.arguments?.[0] &&
        ts.isObjectLiteralExpression(node.arguments[0])
    ) {
        for (const property of node.arguments[0].properties) {
            if (ts.isMethodDeclaration(property)) {
                editorLifecycleHooks.push(propertyName(hocusSource, property));
            }
        }
    }
    ts.forEachChild(node, visitHocus);
};
visitHocus(hocusSource);

const validatorImports = collectImports("src/validators/index.ts");
assertModulesImported("src/validators", "@/validators", validatorImports);

const runtimeImports = collectImports("src/imports.ts", "src/events/index.ts", "src/routes/index.ts", "src/consumers/index.ts");
assertModulesImported("src/events", "@/events", runtimeImports);
assertModulesImported("src/routes", "@/routes", runtimeImports);
assertModulesImported("src/consumers", "@/consumers", runtimeImports);

assert.equal(new Set(registeredTopics).size, registeredTopics.length, "A socket topic validator is registered more than once");
assert.deepEqual(sorted(registeredTopics), sorted(contract.runtime.validated_topics));

for (const command of clientCommands) {
    assert(
        command.topic === contract.topics.none || registeredTopics.includes(command.topic),
        `Client command topic ${command.topic} has no validator`
    );
}
assert.equal(new Set(clientCommands.map(({ topic, event }) => `${topic}:${event}`)).size, clientCommands.length);
assert.deepEqual(sorted(clientCommands), sorted(contract.runtime.client_commands));
assert.deepEqual(sorted(httpRoutes), sorted(contract.runtime.http_routes));
assert.deepEqual(sorted(brokerConsumers), sorted(contract.runtime.broker_consumers));
assert.deepEqual(sorted(editorLifecycleHooks), sorted(contract.runtime.editor_sync.lifecycle_hooks));

const socketManagerSource = fs.readFileSync("src/core/server/SocketManager.ts", "utf8");
assert(socketManagerSource.includes(`"${contract.runtime.editor_sync.websocket_path}"`), "Editor sync WebSocket path is missing from SocketManager");

const kafkaConsumerSource = parse("src/core/broadcast/KafkaConsumer.ts");
const brokerSchemaVersion = variableInitializer(kafkaConsumerSource, "BROKER_ENVELOPE_SCHEMA_VERSION");
assert(ts.isStringLiteral(brokerSchemaVersion), "BROKER_ENVELOPE_SCHEMA_VERSION must be a string literal");
assert.equal(brokerSchemaVersion.text, contract.broker_envelope.current_schema_version);

const brokerEnvelopeTypeScript = fs.readFileSync("src/core/broadcast/BrokerEnvelope.ts", "utf8");
const brokerEnvelopeJavaScript = ts.transpileModule(brokerEnvelopeTypeScript, {
    compilerOptions: {
        module: ts.ModuleKind.ESNext,
        target: ts.ScriptTarget.ES2022,
    },
}).outputText;
const { decodeBrokerEnvelope } = await import(`data:text/javascript;base64,${Buffer.from(brokerEnvelopeJavaScript).toString("base64")}`);
const schemaVersion = contract.broker_envelope.current_schema_version;

assert.deepEqual(
    decodeBrokerEnvelope(
        { schema_version: schemaVersion, event_id: "event-1", event: "socket_publish", occurred_at: "2026-09-12T12:00:00Z", data: {} },
        "socket_publish",
        schemaVersion
    ),
    {
        type: "inline",
        data: {},
        eventId: "event-1",
        occurredAt: "2026-09-12T12:00:00Z",
    }
);
assert.deepEqual(decodeBrokerEnvelope({ cache_key: "broadcast-1" }, "socket_publish", schemaVersion), {
    type: "legacy",
    cacheKey: "broadcast-1",
});
assert.equal(
    decodeBrokerEnvelope(
        {
            schema_version: schemaVersion,
            event_id: "event-1",
            event: "notification_publish",
            occurred_at: "2026-09-12T12:00:00Z",
            data: {},
            cache_key: "broadcast-1",
        },
        "socket_publish",
        schemaVersion
    ),
    null
);
assert.equal(
    decodeBrokerEnvelope(
        {
            schema_version: "unsupported",
            event_id: "event-1",
            event: "socket_publish",
            occurred_at: "2026-09-12T12:00:00Z",
            data: {},
            cache_key: "broadcast-1",
        },
        "socket_publish",
        schemaVersion
    ),
    null
);
assert.equal(
    decodeBrokerEnvelope(
        { schema_version: schemaVersion, event_id: "event-1", event: "socket_publish", occurred_at: "invalid", data: {} },
        "socket_publish",
        schemaVersion
    ),
    null
);
assert.equal(decodeBrokerEnvelope({ cache_key: "" }, "socket_publish", schemaVersion), null);
