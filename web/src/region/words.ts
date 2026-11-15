import type { components } from "../api/schema";

export type Locale = components["schemas"]["Locale"];
type NoteFormat = components["schemas"]["NoteFormat"];

export interface Words {
  ward: string;
  bed: string;
  recordNumber: string;
  endorsement: string;
  patientsHeading: string;
  medicine: string;
  doctor: string;
  noteFormat: (format: NoteFormat) => string;
}

const NOTE_FORMATS: Record<Locale, Record<NoteFormat, string>> = {
  "en-PH": { fdar: "FDAR" },
  "en-US": { fdar: "DAR" },
};

const WORDS: Record<Locale, Omit<Words, "noteFormat">> = {
  "en-PH": {
    ward: "Ward",
    bed: "Bed",
    recordNumber: "Hospital no.",
    endorsement: "Endorsement",
    patientsHeading: "Patients on this ward",
    medicine: "Medicine",
    doctor: "Doctor",
  },
  "en-US": {
    ward: "Unit",
    bed: "Room",
    recordNumber: "MRN",
    endorsement: "Handoff",
    patientsHeading: "Patients on this unit",
    medicine: "Medication",
    doctor: "Provider",
  },
};

/** The facility's words for the screens. The locale comes from its profile, never the browser. */
export function words(locale: Locale): Words {
  return { ...WORDS[locale], noteFormat: (format) => NOTE_FORMATS[locale][format] };
}
