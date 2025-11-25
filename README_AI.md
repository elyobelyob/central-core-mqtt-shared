RAW AI README (COPY/PASTE DIRECTLY)

Central-Core Integration Guide for AI Agents

This project is part of the central-core ecosystem, consisting of:

Vault (central controller)

Hub (remote device connected to Home Assistant)

Addon (Home Assistant plugin)

central-core-mqtt-shared (shared MQTT protocol)

All AI agents working on this repository must follow this guide.

Purpose of This Repository

This repository is one of the following components:

Vault

Hub

Addon (Home Assistant plugin)

It must integrate with the MQTT protocol defined in:

https://github.com/elyobelyob/central-core-mqtt-shared

This repo must import:

from central_core_mqtt_shared import topics, schemas

Everything must conform to the schemas and topics defined there.

Required System Behavior

2.1 Topics
All MQTT communication uses versioned topics:

hubs/{hub_id}/v{version}/...

Topics are defined in central-core-mqtt-shared/topics.py.

The project must use build_topic() to generate all concrete MQTT topics.

Sensor Handling Rules

Home Assistant provides:

Basic sensor list

Full metadata only when polled or when state changes

Your project must support:

A. Basic sensor payload
partial = true
Minimal data for all sensors.

B. Delta updates
partial = true
Only changed sensors.

C. Full metadata
partial = false
Complete details returned only when:

Vault polls the Hub

HA fires a rich metadata event

Schemas for this are in:
schemas.SensorsTelemetry
schemas.BasicSensor
schemas.FullSensor

Commands and Acknowledgements

The component must:

Validate all incoming commands using Pydantic models

Respond with CommandAck on success or error

Always include command_id

Always publish to the correct ack topic:

hubs/{hub_id}/v{version}/ack/{command_name}/{command_id}

Commands defined in:
schemas.ConfigUpdateCommand
schemas.FirmwareUpdateCommand
schemas.TunnelStartCommand
schemas.TunnelStopCommand
schemas.SensorsPollCommand
schemas.SensorsSetCommand
schemas.HAAddonCommand

Responsibilities Per Component

5.1 Vault

Vault must:

Subscribe to all telemetry + status topics

Request sensor metadata via CMD_SENSORS_POLL

Maintain a sensor registry per hub

Merge:

basic sensor lists

full metadata

delta updates

Validate all payloads using schemas

Track all acknowledgements

5.2 Hub

Hub must:

Connect to Home Assistant API

Publish:

basic sensor list

full metadata (on poll/change)

delta changes

Respond to commands:

config update

firmware update

tunnel control

sensor poll

Send command acknowledgements

Validate all incoming commands

5.3 Addon (Home Assistant plugin)

Addon must:

Interface with HA to gather state + attributes

Notify Hub of:

sensor events

full metadata

changes

Publish addon telemetry + status via MQTT

Process addon-specific commands

Validate all payloads using schemas

Import rules

Always import the shared MQTT library like this:

from central_core_mqtt_shared import topics, schemas
from central_core_mqtt_shared.topics import build_topic

Do not redefine schemas or topics locally.

Message Validation

Every incoming MQTT payload must be validated:

payload = schemas.Payload(**json_dict)

This guarantees:

correct structure

correct required fields

prevents invalid data from corrupting system state

Project Tasks for AI Agents

AI agents working on this repo must:

Review the MQTT shared repo

Implement all required imports from central_core_mqtt_shared

Ensure all MQTT messages are validated via Pydantic

Implement sensor logic (basic + delta + full metadata)

Implement command logic

Implement acknowledgements

Update documentation as needed

Maintain version compatibility

Error Handling Requirements

Your component must:

Log invalid payloads

Reject malformed messages

Send ack with "error" status when needed

Never crash due to MQTT data

Re-sync sensor metadata if missing

Completion Criteria

This repository is considered correctly integrated when:

All MQTT handlers use schemas

All commands send acknowledgements

Sensor registry behavior is correct

All metadata can be retrieved on demand

The project uses versioned MQTT topics

The project has no duplicated protocol code

Everything imports correctly from central-core-mqtt-shared

Reference Repository

Shared protocol definitions:

https://github.com/elyobelyob/central-core-mqtt-shared

This repository supersedes all previous protocol code.

END OF AI INTEGRATION README
