import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it } from "vitest";
import { facilityQuery } from "../facility/useFacility";
import { demoApi } from "../mocks/demo-api";
import { MOCK_EMAILS } from "../mocks/staff";
import { renderApp } from "../test/render";
import { server } from "../test/setup";
import { pageStatus } from "../test/status";
import { chooseAndUnlock, DEMO_PIN, demoPinHint } from "../test/signIn";

afterEach(() => {
  server.events.removeAllListeners();
});

/** Signs in as the admin. `before` runs once the mock is in place, to change what it answers. */
async function openSettings(before?: () => void) {
  const view = await renderApp("/sign-in");
  before?.();
  await chooseAndUnlock("Admin · Victor Lazaro");
  await screen.findByRole("heading", { name: "Settings" });
  const name = await screen.findByRole("textbox", { name: "Facility name" });
  return { ...view, name };
}

/** Presses Save settings, and gives the PIN in the dialog that asks for it. */
async function saveWithPin(pin = DEMO_PIN) {
  await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
  const dialog = await screen.findByRole("dialog", {
    name: "Enter your PIN to save these settings",
  });
  await userEvent.type(within(dialog).getByLabelText("Your PIN"), pin);
  await userEvent.click(within(dialog).getByRole("button", { name: "Save settings" }));
}

function shift(n: number) {
  return screen.getByRole("group", { name: `Shift ${String(n)}` });
}

function refuse(status: number, code: string, errors?: { field: string; message: string }[]) {
  return HttpResponse.json(
    { type: "about:blank", title: "No", status, code, ...(errors ? { errors } : {}) },
    { status, headers: { "Content-Type": "application/problem+json" } },
  );
}

/** Counts the PUTs the screen sends. */
function countPuts() {
  const seen = { count: 0 };
  server.events.on("request:start", ({ request }) => {
    if (request.method === "PUT") seen.count += 1;
  });
  return seen;
}

describe("the settings screen", () => {
  it("shows the first facility's settings in a form", async () => {
    const { name } = await openSettings();
    expect(name).toHaveValue("SYNTHETIC Demo Hospital (PH)");
    expect(screen.getByRole("combobox", { name: "Facility" })).toHaveDisplayValue(
      "SYNTHETIC Demo Hospital (PH)",
    );
    expect(screen.getByRole("combobox", { name: "Timezone" })).toHaveValue("Asia/Manila");
    expect(screen.getByRole("radio", { name: "English (Philippines)" })).toBeChecked();
    expect(screen.getByLabelText("Nursing day starts")).toHaveValue("06:00");
    expect(within(shift(3)).getByLabelText("Code")).toHaveValue("10-6");
    expect(within(shift(3)).getByLabelText("Starts")).toHaveValue("22:00");
    expect(within(shift(3)).getByRole("radio", { name: "Red" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "°C" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "24-hour" })).toBeChecked();
    expect(screen.getByText("FDAR")).toBeVisible();
    expect(screen.getByText("More formats come later")).toBeVisible();
    expect(
      screen.getByText("Changes apply to new notes. Notes already written keep their shift."),
    ).toBeVisible();
  });

  it("saves a renamed label, says Saved and marks the facility queries stale", async () => {
    const { name, queryClient } = await openSettings();
    await queryClient.query(facilityQuery("ph-demo"));
    const label = within(shift(3)).getByLabelText("Label");
    await userEvent.clear(label);
    await userEvent.type(label, "Night");
    await saveWithPin();
    const status = pageStatus();
    await waitFor(() => {
      expect(status).toHaveTextContent("Saved.");
    });
    expect(status).toHaveTextContent("version 2");
    expect(name).toHaveValue("SYNTHETIC Demo Hospital (PH)");
    expect(queryClient.getQueryState(facilityQuery("ph-demo").queryKey)?.isInvalidated).toBe(true);
    // The next save goes against the new version, so it is accepted too.
    await userEvent.type(label, "s");
    await saveWithPin();
    await waitFor(() => {
      expect(status).toHaveTextContent("version 3");
    });
  });

  it("shows a gap above the shifts table and does not send the form", async () => {
    await openSettings();
    const puts = countPuts();
    fireEvent.change(within(shift(2)).getByLabelText("Starts"), { target: { value: "15:00" } });
    const problem = await screen.findByText("There's a gap between 14:00 and 15:00.");
    expect(problem).toBeVisible();
    // Above the first shift, inside the shifts table.
    expect(screen.getByRole("group", { name: "Shifts" })).toContainElement(problem);
    expect(
      problem.compareDocumentPosition(shift(1)) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
    expect(problem).toBeVisible();
    expect(document.getElementById("shift-problems")).toHaveFocus();
    expect(puts.count).toBe(0);
  });

  it("words the shift problems in the clock being edited", async () => {
    await openSettings();
    fireEvent.change(within(shift(2)).getByLabelText("Starts"), { target: { value: "15:00" } });
    expect(await screen.findByText("There's a gap between 14:00 and 15:00.")).toBeVisible();
    await userEvent.click(screen.getByRole("radio", { name: "12-hour" }));
    expect(await screen.findByText("There's a gap between 2 PM and 3 PM.")).toBeVisible();
    expect(screen.queryByText("There's a gap between 14:00 and 15:00.")).toBeNull();
    await userEvent.click(screen.getByRole("radio", { name: "24-hour" }));
    expect(await screen.findByText("There's a gap between 14:00 and 15:00.")).toBeVisible();
  });

  it("checks every field before it sends the form", async () => {
    await openSettings();
    const puts = countPuts();
    const nameField = screen.getByRole("textbox", { name: "Facility name" });
    await userEvent.clear(nameField);
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
    expect(nameField).toHaveAccessibleDescription("Enter the facility's name.");
    expect(nameField).toBeInvalid();
    expect(nameField).toHaveFocus();
    expect(puts.count).toBe(0);
  });

  it("turns away a timezone nobody knows", async () => {
    await openSettings();
    const puts = countPuts();
    const zone = screen.getByRole("combobox", { name: "Timezone" });
    await userEvent.clear(zone);
    await userEvent.type(zone, "Mars/Base");
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
    expect(zone).toHaveAccessibleDescription("Enter a real timezone, such as Europe/Paris.");
    expect(zone).toBeInvalid();
    expect(puts.count).toBe(0);
  });

  it("saves a label rename for a facility whose zone is UTC, and suggests UTC", async () => {
    await openSettings(() => {
      const stored = structuredClone(demoApi.facilities["ph-demo"]);
      if (!stored) throw new Error("no demo facility");
      stored.profile.timezone = "UTC";
      server.use(
        http.get("*/api/v1/facilities/:key", () =>
          HttpResponse.json(stored, { headers: { ETag: '"f1"' } }),
        ),
      );
    });
    expect(screen.getByRole("combobox", { name: "Timezone" })).toHaveValue("UTC");
    expect(document.querySelector('#timezone-list option[value="UTC"]')).not.toBeNull();
    const label = within(shift(3)).getByLabelText("Label");
    await userEvent.clear(label);
    await userEvent.type(label, "Night");
    await saveWithPin();
    await waitFor(() => {
      expect(pageStatus()).toHaveTextContent("Saved.");
    });
    expect(screen.getByRole("combobox", { name: "Timezone" })).toHaveValue("UTC");
  });

  it("says what to do for a refusal that names no field, and for one the server blames on the account", async () => {
    await openSettings();
    server.use(http.put("*/api/v1/facilities/:key", () => refuse(422, "invalid_request", [])));
    await saveWithPin();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The server did not accept the settings and named no field. Check each field, then try again.",
    );
    server.use(http.put("*/api/v1/facilities/:key", () => refuse(403, "forbidden")));
    await saveWithPin();
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        "This account can't change settings. Sign out, then sign in as the admin.",
      );
    });
  });

  it("says a save refused for a stale token was not made, and to try again", async () => {
    await openSettings();
    server.use(http.put("*/api/v1/facilities/:key", () => refuse(403, "csrf_failed")));
    await saveWithPin();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The settings were not saved. Try again.",
    );
    expect(screen.queryByText(/sign in as the admin/)).toBeNull();
  });

  it("offers Try again when one facility's settings do not load", async () => {
    await renderApp("/sign-in");
    server.use(
      http.get("*/api/v1/facilities/:key", () => refuse(404, "not_found"), { once: true }),
    );
    await chooseAndUnlock("Admin · Victor Lazaro");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("This facility's settings did not load.");
    await userEvent.click(within(alert).getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("textbox", { name: "Facility name" })).toHaveValue(
      "SYNTHETIC Demo Hospital (PH)",
    );
  });

  it("shows the server's field error next to its field and focuses it", async () => {
    await openSettings();
    server.use(
      http.put("*/api/v1/facilities/:key", () =>
        refuse(422, "invalid_request", [
          { field: "body.shifts.1.label", message: "A label is 1 to 40 characters." },
        ]),
      ),
    );
    await saveWithPin();
    const label = within(shift(2)).getByLabelText("Label");
    await waitFor(() => {
      expect(label).toHaveAccessibleDescription("A label is 1 to 40 characters.");
    });
    expect(label).toBeInvalid();
    expect(label).toHaveFocus();
    expect(within(shift(1)).getByLabelText("Label")).toBeValid();
  });

  it("shows an error on the whole form above the shifts table", async () => {
    await openSettings();
    server.use(
      http.put("*/api/v1/facilities/:key", () =>
        refuse(422, "invalid_request", [
          { field: "body", message: "Shifts must cover 24 hours with no gap or overlap." },
        ]),
      ),
    );
    await saveWithPin();
    const message = await screen.findByText("Shifts must cover 24 hours with no gap or overlap.");
    const table = screen.getByRole("group", { name: "Shifts" });
    expect(table).toContainElement(message);
    const first = within(table).getByRole("group", { name: "Shift 1" });
    expect(message.compareDocumentPosition(first) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("keeps the form after a 412", async () => {
    const { name } = await openSettings();
    server.use(
      http.put("*/api/v1/facilities/:key", () => refuse(412, "stale_version"), { once: true }),
    );
    await userEvent.clear(name);
    await userEvent.type(name, "SYNTHETIC Edited Name");
    await saveWithPin();
    expect(
      await screen.findByText("Someone else changed the settings. Reload to see them."),
    ).toBeVisible();
    expect(name).toHaveValue("SYNTHETIC Edited Name");
    await userEvent.click(screen.getByRole("button", { name: "Reload settings" }));
    await waitFor(() => {
      expect(name).toHaveValue("SYNTHETIC Demo Hospital (PH)");
    });
    expect(screen.queryByRole("button", { name: "Reload settings" })).toBeNull();
  });

  it("adds and removes a shift", async () => {
    await openSettings();
    await userEvent.click(screen.getByRole("button", { name: "Add a shift" }));
    expect(shift(4)).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Remove shift 2-10" }));
    expect(screen.queryByRole("group", { name: "Shift 4" })).toBeNull();
    expect(within(shift(2)).getByLabelText("Code")).toHaveValue("10-6");
  });

  it("asks before it drops unsaved changes, with Keep editing focused first", async () => {
    const { name } = await openSettings();
    await userEvent.type(name, "!");
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Facility" }), "us-demo");
    const dialog = await screen.findByRole("dialog", { name: "Discard your changes?" });
    expect(within(dialog).getByRole("button", { name: "Keep editing" })).toHaveFocus();
    await userEvent.click(within(dialog).getByRole("button", { name: "Keep editing" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(name).toHaveValue("SYNTHETIC Demo Hospital (PH)!");

    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Facility" }), "us-demo");
    await userEvent.click(await screen.findByRole("button", { name: "Discard changes" }));
    await waitFor(() => {
      expect(screen.getByRole("textbox", { name: "Facility name" })).toHaveValue(
        "SYNTHETIC Demo Hospital (US)",
      );
    });
    expect(screen.getByRole("radio", { name: "°F" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "24-hour" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "English (United States)" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "None" })).toBeChecked();
  });

  it("names the note format in the facility's own words, as its locale is set", async () => {
    await openSettings();
    expect(screen.getByText("FDAR")).toBeVisible();
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Facility" }), "us-demo");
    await waitFor(() => {
      expect(screen.getByRole("textbox", { name: "Facility name" })).toHaveValue(
        "SYNTHETIC Demo Hospital (US)",
      );
    });
    expect(screen.getByText("DAR")).toBeVisible();
    expect(screen.queryByText("FDAR")).toBeNull();
    // It follows the locale picked in the form, before the change is saved.
    await userEvent.click(screen.getByRole("radio", { name: "English (Philippines)" }));
    expect(screen.getByText("FDAR")).toBeVisible();
    expect(screen.queryByText("DAR")).toBeNull();
  });

  it("switches facility without a question when nothing changed", async () => {
    await openSettings();
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Facility" }), "us-demo");
    await waitFor(() => {
      expect(screen.getByRole("textbox", { name: "Facility name" })).toHaveValue(
        "SYNTHETIC Demo Hospital (US)",
      );
    });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("says what to do when the facilities do not load, and shows no form", async () => {
    await renderApp("/sign-in");
    server.use(http.get("*/api/v1/facilities", () => refuse(404, "not_found")));
    await chooseAndUnlock("Admin · Victor Lazaro");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The facilities did not load. Reload the page to try again.",
    );
    expect(screen.queryByRole("button", { name: "Save settings" })).toBeNull();
  });
});

describe("saving with your own PIN", () => {
  /** Keeps the PUTs the screen sends: how many, and the last body. */
  function watchPuts() {
    const seen: { count: number; body: Record<string, unknown> | null } = { count: 0, body: null };
    server.events.on("request:start", ({ request }) => {
      if (request.method !== "PUT") return;
      seen.count += 1;
      void request
        .clone()
        .json()
        .then((body: Record<string, unknown>) => {
          seen.body = body;
        });
    });
    return seen;
  }

  it("asks for the PIN after the form checks out, and sends it flat with the settings", async () => {
    const { name, queryClient } = await openSettings();
    const seen = watchPuts();
    await userEvent.type(name, "!");
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Enter your PIN to save these settings",
    });
    expect(within(dialog).getByLabelText("Your PIN")).toHaveFocus();
    expect(seen.count).toBe(0);
    // A try with another PIN sends that PIN: what is sent is what was typed.
    await userEvent.type(within(dialog).getByLabelText("Your PIN"), "999999{Enter}");
    await within(dialog).findByText("Wrong PIN. 4 tries left.");
    await waitFor(() => {
      expect(seen.body).toMatchObject({ pin: "999999", name: "SYNTHETIC Demo Hospital (PH)!" });
    });
    await userEvent.type(within(dialog).getByLabelText("Your PIN"), `${DEMO_PIN}{Enter}`);
    await waitFor(() => {
      expect(pageStatus()).toHaveTextContent("Saved.");
    });
    expect(seen.body).toMatchObject({
      pin: DEMO_PIN,
      name: "SYNTHETIC Demo Hospital (PH)!",
      session_max_hours: 12,
    });
    expect(screen.queryByRole("dialog")).toBeNull();
    await waitFor(() => {
      expect(JSON.stringify(queryClient.getMutationCache().getAll())).not.toContain(DEMO_PIN);
    });
  });

  it("shows a demo person the demo PIN in the PIN question, and a Google user none", async () => {
    await openSettings();
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(demoPinHint())).toBeVisible();
    expect(within(dialog).getByLabelText("Your PIN")).toHaveAccessibleDescription(
      expect.stringContaining(`Demo PIN: ${DEMO_PIN}`),
    );
  });

  it("gives the focus back to Save settings after a gap was fixed and the PIN question closed", async () => {
    await openSettings();
    fireEvent.change(within(shift(2)).getByLabelText("Starts"), { target: { value: "15:00" } });
    await screen.findByText("There's a gap between 14:00 and 15:00.");
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
    expect(document.getElementById("shift-problems")).toHaveFocus();
    fireEvent.change(within(shift(2)).getByLabelText("Starts"), { target: { value: "14:00" } });
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Save settings" })).toHaveFocus();
    });
  });

  it("does not ask while the form still has a problem", async () => {
    await openSettings();
    const nameField = screen.getByRole("textbox", { name: "Facility name" });
    await userEvent.clear(nameField);
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("does not send fewer than 6 digits", async () => {
    await openSettings();
    const seen = watchPuts();
    await saveWithPin("1357");
    expect(await screen.findByText("Enter your 6-digit PIN.")).toBeVisible();
    expect(seen.count).toBe(0);
    expect(screen.getByRole("dialog")).toBeVisible();
  });

  it("a wrong PIN keeps every typed setting, clears the PIN and says the tries left", async () => {
    const { name } = await openSettings();
    await userEvent.type(name, "!");
    const label = within(shift(3)).getByLabelText("Label");
    await userEvent.clear(label);
    await userEvent.type(label, "Night");
    await userEvent.type(
      screen.getByLabelText("Sign nurses out after (hours)"),
      "{Backspace}{Backspace}8",
    );
    await saveWithPin("999999");
    const dialog = screen.getByRole("dialog");
    expect(await within(dialog).findByText("Wrong PIN. 4 tries left.")).toBeVisible();
    const field = within(dialog).getByLabelText("Your PIN");
    expect(field).toHaveValue("");
    await waitFor(() => {
      expect(field).toHaveFocus();
    });
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
    expect(name).toHaveValue("SYNTHETIC Demo Hospital (PH)!");
    expect(label).toHaveValue("Night");
    expect(screen.getByLabelText("Sign nurses out after (hours)")).toHaveValue(8);
    // Trying again with the right PIN saves all of it.
    await saveWithPin();
    await waitFor(() => {
      expect(pageStatus()).toHaveTextContent("Saved.");
    });
    expect(name).toHaveValue("SYNTHETIC Demo Hospital (PH)!");
  });

  it("Cancel sends nothing and leaves the form as it was", async () => {
    const { name } = await openSettings();
    const seen = watchPuts();
    await userEvent.type(name, "!");
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
    expect(seen.count).toBe(0);
    expect(name).toHaveValue("SYNTHETIC Demo Hospital (PH)!");
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Save settings" })).toHaveFocus();
    });
  });

  it("closes the question on a 412 and says so in the form, as before", async () => {
    const { name } = await openSettings();
    server.use(
      http.put("*/api/v1/facilities/:key", () => refuse(412, "stale_version"), { once: true }),
    );
    await userEvent.type(name, "!");
    await saveWithPin();
    expect(
      await screen.findByText("Someone else changed the settings. Reload to see them."),
    ).toBeVisible();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(name).toHaveValue("SYNTHETIC Demo Hospital (PH)!");
  });

  it("sends a demo person back to sign-in after the fifth wrong PIN", async () => {
    const { name } = await openSettings();
    await userEvent.type(name, "!");
    for (let i = 0; i < 4; i += 1) {
      await saveWithPin("999999");
      await screen.findByText(new RegExp(`^Wrong PIN\\. ${String(4 - i)} tr`));
    }
    await userEvent.type(screen.getByLabelText("Your PIN"), "999999{Enter}");
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeVisible();
  });
});

describe("how long a session lasts", () => {
  const HOURS = "Sign nurses out after (hours)";

  it("shows each facility's preset, with what a change does", async () => {
    await openSettings();
    const hours = screen.getByLabelText(HOURS);
    expect(hours).toHaveValue(12);
    expect(hours).toHaveAccessibleDescription("Applies to sessions that start after you save.");
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Facility" }), "us-demo");
    await waitFor(() => {
      expect(screen.getByRole("textbox", { name: "Facility name" })).toHaveValue(
        "SYNTHETIC Demo Hospital (US)",
      );
    });
    expect(screen.getByLabelText(HOURS)).toHaveValue(14);
  });

  it.each([
    ["0", "Enter 1 to 24 hours."],
    ["25", "Enter 1 to 24 hours."],
    ["1.5", "Enter whole hours."],
    ["", "Enter 1 to 24 hours."],
  ])("refuses %j before it asks for a PIN", async (typed, message) => {
    await openSettings();
    const hours = screen.getByLabelText(HOURS);
    await userEvent.clear(hours);
    if (typed) await userEvent.type(hours, typed);
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
    expect(hours).toBeInvalid();
    expect(hours).toHaveAccessibleDescription(expect.stringContaining(message));
    expect(hours).toHaveFocus();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it.each([1, 24])("saves %i hours", async (count) => {
    await openSettings();
    const hours = screen.getByLabelText(HOURS);
    await userEvent.clear(hours);
    await userEvent.type(hours, String(count));
    await saveWithPin();
    await waitFor(() => {
      expect(pageStatus()).toHaveTextContent("Saved.");
    });
    expect(hours).toHaveValue(count);
    expect(demoApi.facilities["ph-demo"]?.profile.session_max_hours).not.toBe(count);
  });

  it("shows the server's word on the hours field", async () => {
    await openSettings();
    server.use(
      http.put("*/api/v1/facilities/:key", () =>
        refuse(422, "invalid_request", [
          { field: "body.session_max_hours", message: "Enter 1 to 24 hours." },
        ]),
      ),
    );
    await saveWithPin();
    const hours = screen.getByLabelText(HOURS);
    await waitFor(() => {
      expect(hours).toHaveAccessibleDescription(expect.stringContaining("Enter 1 to 24 hours."));
    });
    expect(hours).toHaveFocus();
  });
});

describe("Reset demo settings", () => {
  const RESET = { name: "Reset demo settings" };

  it("is there for the demo's admin, as a secondary button beside Save settings", async () => {
    await openSettings();
    const reset = screen.getByRole("button", RESET);
    expect(reset).toBeVisible();
    expect(reset.className).not.toContain("bg-primary");
    expect(screen.getByRole("button", { name: "Save settings" }).className).toContain("bg-primary");
  });

  it("puts the settings back to the preset after a PIN, and says so", async () => {
    const { name } = await openSettings();
    // First save a change, so there is something to put back.
    await userEvent.type(name, "!");
    await saveWithPin();
    await waitFor(() => {
      expect(pageStatus()).toHaveTextContent("version 2");
    });
    expect(name).toHaveValue("SYNTHETIC Demo Hospital (PH)!");

    await userEvent.click(screen.getByRole("button", RESET));
    const dialog = await screen.findByRole("dialog", { name: "Reset demo settings" });
    expect(
      within(dialog).getByText("Put this facility's settings back to how the demo started?"),
    ).toBeVisible();
    expect(within(dialog).getByLabelText("Your PIN")).toHaveFocus();
    await userEvent.type(within(dialog).getByLabelText("Your PIN"), `${DEMO_PIN}{Enter}`);
    await waitFor(() => {
      expect(name).toHaveValue("SYNTHETIC Demo Hospital (PH)");
    });
    expect(pageStatus()).toHaveTextContent("Settings are back to how the demo started.");
    expect(screen.queryByRole("dialog")).toBeNull();
    // The next save goes against the version the reset returned.
    await userEvent.type(name, "?");
    await saveWithPin();
    await waitFor(() => {
      expect(pageStatus()).toHaveTextContent("Saved.");
    });
  });

  it("says that changes not yet saved are dropped, only when there are some", async () => {
    const { name } = await openSettings();
    await userEvent.click(screen.getByRole("button", RESET));
    let dialog = await screen.findByRole("dialog", { name: "Reset demo settings" });
    expect(within(dialog).queryByText(/aren't saved/)).toBeNull();
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
    await userEvent.type(name, "!");
    await userEvent.click(screen.getByRole("button", RESET));
    dialog = await screen.findByRole("dialog", { name: "Reset demo settings" });
    expect(within(dialog).getByText("Changes you haven't saved are dropped.")).toBeVisible();
  });

  it("keeps the PIN out of TanStack's mutation cache", async () => {
    const { queryClient } = await openSettings();
    await userEvent.click(screen.getByRole("button", RESET));
    const dialog = await screen.findByRole("dialog", { name: "Reset demo settings" });
    await userEvent.type(within(dialog).getByLabelText("Your PIN"), `${DEMO_PIN}{Enter}`);
    await waitFor(() => {
      expect(pageStatus()).toHaveTextContent("Settings are back to how the demo started.");
    });
    await waitFor(() => {
      expect(JSON.stringify(queryClient.getMutationCache().getAll())).not.toContain(DEMO_PIN);
    });
  });

  it("shows the demo PIN in the reset question, and says the dropped changes in its description", async () => {
    const { name } = await openSettings();
    await userEvent.type(name, "!");
    await userEvent.click(screen.getByRole("button", RESET));
    const dialog = await screen.findByRole("dialog", { name: "Reset demo settings" });
    expect(within(dialog).getByText(demoPinHint())).toBeVisible();
    expect(dialog).toHaveAccessibleDescription(
      "Put this facility's settings back to how the demo started? Changes you haven't saved are dropped.",
    );
  });

  it("a wrong PIN keeps the dialog open and says the tries left", async () => {
    await openSettings();
    await userEvent.click(screen.getByRole("button", RESET));
    const dialog = await screen.findByRole("dialog", { name: "Reset demo settings" });
    await userEvent.type(within(dialog).getByLabelText("Your PIN"), "999999{Enter}");
    expect(await within(dialog).findByText("Wrong PIN. 4 tries left.")).toBeVisible();
    expect(within(dialog).getByLabelText("Your PIN")).toHaveValue("");
  });

  it("says a reset refused for a stale token was not made, and to try again", async () => {
    await openSettings();
    server.use(http.post("*/api/v1/facilities/:key/reset", () => refuse(403, "csrf_failed")));
    await userEvent.click(screen.getByRole("button", RESET));
    const dialog = await screen.findByRole("dialog", { name: "Reset demo settings" });
    await userEvent.type(within(dialog).getByLabelText("Your PIN"), `${DEMO_PIN}{Enter}`);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The settings were not put back. Try again.",
    );
    expect(screen.queryByText(/demo's admin/)).toBeNull();
  });

  it("shows a Google admin no demo PIN in the save question", async () => {
    await renderApp("/settings", { account: { user: MOCK_EMAILS.admin, gate: "open" } });
    await screen.findByRole("textbox", { name: "Facility name" });
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText("Your PIN")).toBeVisible();
    expect(within(dialog).queryByText(/Demo PIN/)).toBeNull();
  });

  it("is not there for a Google admin", async () => {
    await renderApp("/settings", { account: { user: MOCK_EMAILS.admin, gate: "open" } });
    await screen.findByRole("textbox", { name: "Facility name" });
    expect(screen.getByRole("button", { name: "Save settings" })).toBeVisible();
    expect(screen.queryByRole("button", RESET)).toBeNull();
  });

  it("is not there when the demo is off", async () => {
    await renderApp("/sign-in", { demo: false });
    await chooseAndUnlock("Admin · Victor Lazaro");
    await screen.findByRole("textbox", { name: "Facility name" });
    expect(screen.queryByRole("button", RESET)).toBeNull();
  });
});

describe("who sees Settings", () => {
  it("a nurse has no Settings link", async () => {
    await renderApp("/sign-in");
    await chooseAndUnlock("Staff nurse · Sarah Navarro, RN");
    const header = await screen.findByRole("banner");
    expect(await within(header).findByRole("link", { name: "Patients" })).toBeVisible();
    expect(within(header).queryByRole("link", { name: "Settings" })).toBeNull();
  });
});
