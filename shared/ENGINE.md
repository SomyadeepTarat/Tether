# Integrated engine boundary

The partner engine is now present. Use shared/INTEGRATION.md, shared/contracts/ and docs/LIFECYCLE_UPDATE.md as the engine contract. Backend imports engine.orchestrator.run_step/run_specialist_step and engine.llm_client.create_inference_client. The old simplified Proposal inference schema has been removed.

AppStore extends the canonical engine Store, adding product metadata and telemetry redaction. Database connections are created and closed in the same FastAPI worker thread. Inference occurs outside write transactions. Durable project step claims prevent overlapping local generation; action keys replay historical engine results without contacting a provider.

The frontend receives a projection for display plus full action/validation data. It does not supply fixture data, contract state, validation decisions or approval actors. Goal-change and milestone confirmations use a backend-granted same-site local operator session. Do not expose services beyond loopback without adding real multi-user authentication.

Engine ALLOW commits exact supported quotations. REVIEW remains uncommitted; user rejection is separately audited. Semantic approval cannot override the gateway and is deliberately unavailable until implemented in the engine. Old dashboard contracts/actions/reports are backed up and archived during migration, not silently trusted against the new evidence fixture.

INFERENCE_COMPLETED precedes outcome recording, including specialist phases and failed attempts. Provider/model/agent/fallback attribution is persisted and shown historically. No raw prompts, responses or credentials enter product audit events.
