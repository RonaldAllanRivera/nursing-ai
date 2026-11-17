import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it } from "vitest";
import { facilityQuery } from "../facility/useFacility";
import { demoApi } from "../mocks/demo-api";
import { renderApp } from "../test/render";
import { server } from "../test/setup";
import { pageStatus } from "../test/status";
import { chooseAndUnlock } from "../test/signIn";

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
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
    const status = pageStatus();
    await waitFor(() => {
      expect(status).toHaveTextContent("Saved.");
    });
    expect(status).toHaveTextContent("version 2");
    expect(name).toHaveValue("SYNTHETIC Demo Hospital (PH)");
    expect(queryClient.getQueryState(facilityQuery("ph-demo").queryKey)?.isInvalidated).toBe(true);
    // The next save goes against the new version, so it is accepted too.
    await userEvent.type(label, "s");
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
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
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
    await waitFor(() => {
      expect(pageStatus()).toHaveTextContent("Saved.");
    });
    expect(screen.getByRole("combobox", { name: "Timezone" })).toHaveValue("UTC");
  });

  it("says what to do for a refusal that names no field, and for one the server blames on the account", async () => {
    await openSettings();
    server.use(http.put("*/api/v1/facilities/:key", () => refuse(422, "invalid_request", [])));
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The server did not accept the settings and named no field. Check each field, then try again.",
    );
    server.use(http.put("*/api/v1/facilities/:key", () => refuse(403, "forbidden")));
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        "This account can't change settings. Sign out, then sign in as the admin.",
      );
    });
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
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
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
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
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
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
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

describe("who sees Settings", () => {
  it("a nurse has no Settings link", async () => {
    await renderApp("/sign-in");
    await chooseAndUnlock("Staff nurse · Sarah Navarro, RN");
    const header = await screen.findByRole("banner");
    expect(await within(header).findByRole("link", { name: "Patients" })).toBeVisible();
    expect(within(header).queryByRole("link", { name: "Settings" })).toBeNull();
  });
});
