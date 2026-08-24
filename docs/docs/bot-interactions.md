# Bot interactions

Langboard bots are service identities that interact with a board in two directions:

- A **hook** subscribes a bot to named events on a project, column, or card.
- An **action** mutates Langboard through the normal API and records the bot as the author.

This is one interaction model, not separate automation products. Schedules are time-based
triggers for the same bot identity. Outbound webhooks are compatibility endpoints for systems
that cannot act as a Langboard bot.

## Canonical hook API

`PUT /bots/{bot_uid}/hooks` converges one subscription identified by the bot and target.
Calling it again updates the event set and active state instead of creating a duplicate.

```json
{
  "target_table": "card",
  "target_uid": "card-uid",
  "events": ["card_moved", "card_checkitem_checked"],
  "active": true
}
```

The current `BotScope` tables remain the storage model. Existing scope endpoints remain
compatible while clients migrate to the service-level Hook vocabulary.

## Bot-authored projections

Bots should use bounded actions rather than reproduce multi-step board mutations. For example,
`reconcile_card_checklist_projection` converges a named checklist from stable item keys. The
server owns native UIDs and returns a content receipt, so a retry is safe and every visible
change is still authored by the authenticated bot.

## API rules

1. Resources use stable nouns: bots, hooks, actions, deliveries.
2. Commands that synchronize desired state are idempotent.
3. Every mutation has one authenticated user or bot author.
4. Event envelopes carry stable IDs and are delivered at least once.
5. Product-specific identifiers belong in caller-owned projection keys, not Langboard schemas.
