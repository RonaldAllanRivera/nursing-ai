import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, type HttpHandler } from "msw";
import { MOCK_PIN } from "../mocks/staff";
import { renderApp } from "../test/render";

/** Opens the Staff screen signed in (open gate) as this mock staff member. `overrides` win over the mock. */
export const open = (user: string, path = "/staff", overrides: HttpHandler[] = []) =>
  renderApp(path, { account: { user, gate: "open" } }, overrides);

/** The queries for one person's row. The header names the signed-in person too, so look only inside the list. */
export const rowOf = async (name: string) => {
  const list = await screen.findByRole("list", { name: "Staff", hidden: true });
  return within(
    await within(list)
      .findByText(name, { selector: "p" })
      .then((p) => p.closest("li") as HTMLElement),
  );
};

/** In the PIN dialog with this title: type the PIN and press the confirm button. */
export async function giveThePin(dialogName: string | RegExp, confirm: string, pin = MOCK_PIN) {
  const dialog = await screen.findByRole("dialog", { name: dialogName });
  await userEvent.type(within(dialog).getByLabelText("Your PIN"), pin);
  await userEvent.click(within(dialog).getByRole("button", { name: confirm }));
  return dialog;
}

/** A problem answer the way the server words one. */
export function problemAnswer(
  status: number,
  code: string,
  errors?: { field: string; message: string }[],
) {
  return HttpResponse.json(
    { type: "about:blank", title: "No", status, code, ...(errors ? { errors } : {}) },
    { status, headers: { "Content-Type": "application/problem+json" } },
  );
}
