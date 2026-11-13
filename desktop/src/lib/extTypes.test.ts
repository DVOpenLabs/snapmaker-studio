import { describe, expect, it } from "vitest";
import topologyFixture from "./__fixtures__/foundation/topology.json";
import materialViewFixture from "./__fixtures__/foundation/material_view.json";
import observationFixture from "./__fixtures__/foundation/observation.json";
import artifactFixture from "./__fixtures__/foundation/artifact_ref.json";
import derivationFixture from "./__fixtures__/foundation/derivation.json";
import recipeFixture from "./__fixtures__/foundation/virtual_recipe.json";
import capabilitiesFixture from "./__fixtures__/foundation/capability_set.json";
import type { ArtifactRef, CapabilitySet, Derivation, MaterialView, Observation, Topology, VirtualRecipe, CapabilityEvaluation } from "./extTypes";

// JSON fixture literals widen to string/number while retaining every required key.
type Widen<T> = T extends string ? string : T extends number ? number : T extends boolean ? boolean :
  T extends readonly (infer U)[] ? Widen<U>[] : T extends object ? { [K in keyof T]: Widen<T[K]> } : T;
const topology: Widen<Topology> = topologyFixture;
const materialView: Widen<MaterialView> = materialViewFixture;
const observation: Widen<Observation> = observationFixture;
const artifact: Widen<ArtifactRef> = artifactFixture;
const derivation: Widen<Derivation> = derivationFixture;
const recipe: Widen<VirtualRecipe> = recipeFixture;
const capabilities: Widen<CapabilitySet> = capabilitiesFixture;

const rootKeys = [
  [topologyFixture, ["schema_version", "snapshot_id", "received_at", "observed_at", "mapping_revision", "heads", "units", "slots", "bindings", "complete", "evidence", "diagnostics"]],
  [materialViewFixture, ["schema_version", "spool", "fields", "conflicts", "diagnostics"]],
  [observationFixture, ["schema_version", "observation_id", "subject", "field", "value", "source", "source_kind", "observed_at", "received_at", "ttl_s", "ageing_ok", "historical"]],
  [artifactFixture, ["schema_version", "artifact_id", "role", "bytes", "name", "locator", "created_at"]],
  [derivationFixture, ["schema_version", "derivation_id", "output", "inputs", "producer", "witness", "declared_by", "created_at"]],
  [recipeFixture, ["schema_version", "recipe_id", "generator", "kind", "components", "simulated", "execution_supported"]],
  [capabilitiesFixture, ["schema_version", "capabilities"]],
] as const;

const evaluationFixture = {
  inputs_revision: { capability_set: "sha256:abc", requirements: [], scope: {}, revision: "sha256:def" },
  results: [{ key: "multi_head", result: "satisfied", matched: {
    key: "multi_head", state: "supported", scope: { host: null, slicer: null, generator: null, version: null, process: null }, evidence: ["obs-1"],
  }, evidence: ["obs-1"] }],
} satisfies Widen<CapabilityEvaluation>;

describe("foundation TypeScript mirrors", () => {
  it("structurally accepts all seven frozen fixture copies without casts", () => {
    expect([topology.schema_version, materialView.schema_version, observation.schema_version,
      artifact.schema_version, derivation.schema_version, recipe.schema_version, capabilities.schema_version])
      .toEqual(["topology/1", "material_view/1", "observation/1", "artifact_ref/1", "derivation/1", "virtual_recipe/1", "capability_set/1"]);
  });

  it("accepts an observation carrying history_uncertain true", () => {
    const uncertain: Widen<Observation> = { ...observationFixture, history_uncertain: true };
    expect(uncertain.history_uncertain).toBe(true);
    expect(observation.history_uncertain).toBeUndefined();
  });

  it("keeps fixture root keys and required mirror keys in sync in both directions", () => {
    for (const [fixture, declaredKeys] of rootKeys) {
      const fixtureKeys = Object.keys(fixture);
      for (const key of fixtureKeys) expect(declaredKeys, `undeclared fixture key ${key}`).toContain(key);
      for (const key of declaredKeys) expect(fixtureKeys, `missing required fixture key ${key}`).toContain(key);
    }
  });

  it("mirrors the capability evaluation document and revision envelope", () => {
    const typed: Widen<CapabilityEvaluation> = evaluationFixture;
    expect(typed.results[0].result).toBe("satisfied");
    expect(typed.inputs_revision?.revision).toBe("sha256:def");
  });
});
