import type { components } from "../api/schema";

type Persona = components["schemas"]["PersonaOut"];
type Role = components["schemas"]["Role"];

const ROLE_LABELS: Record<Role, string> = {
  staff_nurse: "Staff nurse",
  head_nurse: "Head nurse",
  admin: "Admin",
};

export function roleLabel(role: Role): string {
  return ROLE_LABELS[role];
}

/** `"Staff nurse · Sarah Navarro, RN"`: the role first, the facility is the group's heading. */
export function personaLabel(persona: Persona): string {
  return `${roleLabel(persona.role)} · ${persona.display_name}`;
}

export interface PersonaGroup {
  heading: string;
  personas: Persona[];
}

/** One group per facility (by its name), in the order the API lists them; the admin goes last. */
export function groupPersonas(personas: Persona[]): PersonaGroup[] {
  const byFacility = new Map<string, Persona[]>();
  const everyFacility: Persona[] = [];
  for (const persona of personas) {
    if (persona.facility_key === null || persona.facility_name === null) {
      everyFacility.push(persona);
      continue;
    }
    const group = byFacility.get(persona.facility_name) ?? [];
    group.push(persona);
    byFacility.set(persona.facility_name, group);
  }
  const groups = [...byFacility].map(([heading, list]) => ({ heading, personas: list }));
  if (everyFacility.length > 0) groups.push({ heading: "Every facility", personas: everyFacility });
  return groups;
}
