# Minecraft Management Protocol — Schema Guide

> Snapshot 25w35a — JSON-RPC component schemas summarized with examples.

## How to read this guide
- **Type** shows the JSON type expected for the object or field.
- Unless a field is documented as *required* in your discovery payload, treat fields as optional.
- Examples are **minimal valid** payloads. Replace sample values with yours.

## `untyped_game_rule`
**Type:** object
**Fields:**
- **value**: *string*
- **key**: *string*

**Example:**
```json
{
  "key": "doImmediateRespawn",
  "value": "true"
}
```
**Used by methods:** game rule setters. `typed_game_rule` distinguishes integer vs boolean rule types.

## `incoming_ip_ban`
**Type:** object
**Fields:**
- **reason**: *string*
- **expires**: *string*
- **ip**: *string*
- **source**: *string*
- **player**: *player*

**Example:**
```json
{
  "ip": "203.0.113.42",
  "reason": "DDoS activity",
  "expires": "2025-12-31T23:59:59Z",
  "source": "Console",
  "player": {
    "name": "Griefer",
    "id": "00000000-0000-0000-0000-000000000000"
  }
}
```

## `system_message`
**Type:** object
**Fields:**
- **receivingPlayers**: *array*
- **overlay**: *boolean*
- **message**: *message*

**Example:**
```json
{
  "message": {
    "literal": "Welcome!"
  },
  "overlay": false,
  "receivingPlayers": [
    {
      "name": "Alex",
      "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    }
  ]
}
```
**Used by method:** `minecraft:server/system_message` as the single positional param.
Tip: Set `overlay: true` for action bar; include `receivingPlayers` to target specific players.

## `kick_player`
**Type:** object
**Fields:**
- **players**: *array*
- **message**: *message*

**Example:**
```json
{
  "players": [
    {
      "name": "Steve",
      "id": "11111111-2222-3333-4444-555555555555"
    }
  ],
  "message": {
    "literal": "Be nice. Rejoin later."
  }
}
```
**Used by method:** likely `minecraft:server/kick` or similar (method names may vary).
Tip: Provide `players` as a list of player objects; message is the kick reason.

## `ip_ban`
**Type:** object
**Fields:**
- **reason**: *string*
- **expires**: *string*
- **ip**: *string*
- **source**: *string*

**Example:**
```json
{
  "ip": "198.51.100.24",
  "reason": "Repeated spam",
  "expires": "2025-09-01T00:00:00Z",
  "source": "Admin"
}
```

## `typed_game_rule`
**Type:** object
**Fields:**
- **type**: *string* (enum: integer, boolean)
- **value**: *string*
- **key**: *string*

**Example:**
```json
{
  "key": "playersSleepingPercentage",
  "type": "integer",
  "value": "50"
}
```
**Used by methods:** game rule setters. `typed_game_rule` distinguishes integer vs boolean rule types.

## `user_ban`
**Type:** object
**Fields:**
- **reason**: *string*
- **expires**: *string*
- **source**: *string*
- **player**: *player*

**Example:**
```json
{
  "player": {
    "name": "TroubleMaker",
    "id": "99999999-8888-7777-6666-555555555555"
  },
  "reason": "Hacking",
  "expires": "2025-10-01T00:00:00Z",
  "source": "Moderator"
}
```

## `message`
**Type:** object
**Fields:**
- **translatable**: *string*
- **translatableParams**: *array*
- **literal**: *string*

**Example:**
```json
{
  "literal": "Hello there!"
}
```

## `version`
**Type:** object
**Fields:**
- **protocol**: *integer*
- **name**: *string*

**Example:**
```json
{
  "protocol": 765,
  "name": "25w35a"
}
```

## `server_state`
**Type:** object
**Fields:**
- **players**: *array*
- **started**: *boolean*
- **version**: *version*

**Example:**
```json
{
  "started": true,
  "version": {
    "protocol": 765,
    "name": "25w35a"
  },
  "players": [
    {
      "name": "Alex",
      "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    }
  ]
}
```

## `operator`
**Type:** object
**Fields:**
- **permissionLevel**: *integer*
- **bypassesPlayerLimit**: *boolean*
- **player**: *player*

**Example:**
```json
{
  "player": {
    "name": "Admin",
    "id": "123e4567-e89b-12d3-a456-426614174000"
  },
  "permissionLevel": 4,
  "bypassesPlayerLimit": true
}
```

## `player`
**Type:** object
**Fields:**
- **name**: *string*
- **id**: *string*

**Example:**
```json
{
  "name": "Alex",
  "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
}
```
