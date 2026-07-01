# SimpAI Studio Docs

This directory is split into two kinds of material:

- Project docs that can stay in the repository.
- Local/offline analysis artifacts that should stay on a developer machine and
  are ignored by git.

## Repository Docs

Keep these tracked:

- `web-refactor-goals.md`: long-term WebUI refactor goals.
- `gradio6-native-migration-plan.md`: Gradio 6 migration checkpoints and
  handoff notes.
- `gallery-browser-maintenance.md`: focused runbook for Gradio 6 gallery
  switching, counting, native drag and health-check maintenance.
- `infinite-canvas-workbench-dev-plan.md`: Infinite Canvas design plan.
- `resolution-control-preset-schema.md`: resolution preset/UI contract.
- `sketch-gradio6-dev-log.md`: compressed Sketch migration notes.
- `pose-studio-webui-dev-log.md`: Pose Studio extraction notes for Scene Preset
  integration.
- `vlm-chat-node-dev-plan.md`: VLM chat/canvas agent development plan.
- `vlm-agent-prompt-acceptance.md`: acceptance checklist for VLM prompt flows.
- `vlm-live-matrix-7860-runbook.md`: local validation runbook.
- `random-prompt-tag-stats-maintenance.md`: Random Prompt tag statistics
  rebuild, filter tuning, and validation runbook.
- `staged-update-scripts.md`: staged update package/injector/merge script runbook.
- `agent_guides/create-preset-workflow.md`: coding-agent guide for creating
  SimpAI presets and backend ComfyUI API workflows.
- `director-workspace/README.md`: usage guide and test runbook for the
  Director Workspace and Director Timeline flows.
- `director-workspace/release-matrix-test-plan.md`: release matrix for
  Director Workspace capabilities, media boundaries, WebUI, Infinite Canvas,
  and representative generation checks.
- `gallery-director-manual-test-checklist.md`: manual checklist for recent
  gallery, small UI optimization, real generation preview, and Director
  Workspace validation.
- `readme-showcase.md`: screenshot showcase used by the root README.
- `vlm_skills/`: runtime skill knowledge loaded by the VLM Agent.

Keep these runtime prompt-enrichment data files tracked unless the code is
changed to load them from a different resource directory:

- `sfw_trigger_slots.csv`
- `sfw_negative_conflicts.csv`
- `adult_trigger_slots.csv`
- `adult_negative_conflicts.csv`
- `adult_phrase_trigger_map.csv`
- `vlm_system_prompt_templates.csv`

## Local-Only Artifacts

Do not commit or release generated prompt-mining outputs:

- `adult_association_pairs.csv`
- `adult_branch_quality_cases.csv`
- `adult_branch_quality_samples.csv`
- `adult_association_*.md`
- `adult_branch_quality.md`
- `sfw_association_*.csv`
- `sfw_association_*.md`
- `*_samples.md`
- `*_scratch.md`
- `*_draft.md`
