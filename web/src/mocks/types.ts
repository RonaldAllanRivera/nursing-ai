import type { components } from "../api/schema";

type Schemas = components["schemas"];

/** The demo cases as API answers. demo-api.ts is generated and typed with this. */
export interface DemoApi {
  personas: Schemas["PersonaOut"][];
  /** By persona id. */
  sessions: Record<string, Schemas["SessionOut"]>;
  /** By facility key. */
  facilities: Record<string, Schemas["FacilityOut"]>;
  /** By facility key. */
  patients: Record<"ph-demo" | "us-demo", Schemas["PatientSummary"][]>;
  /** By patient id. */
  patientDetails: Record<string, Schemas["PatientDetail"]>;
  /** By job id. */
  jobs: Record<string, Schemas["DraftJobOut"]>;
  /** By note id. */
  notes: Record<string, Schemas["NoteOut"]>;
  /** By patient id: the job a rough note posted for that patient answers with. */
  jobForPatient: Record<string, string>;
}
