import { describe, expect, it } from "vitest";
import { ApiError, type Problem } from "../api/errors";
import {
  DEMO_ENDED,
  DEMO_EXPIRED,
  PIN_CHANGED,
  demoEndedReason,
  PIN_CONNECTION,
  PIN_LOCKED,
  PIN_NEEDED,
  idleLockWords,
  isPinRefusal,
  isPinTyped,
  pinProblemMessage,
  screenForGate,
} from "./pin";

const problem = (status: number, code: Problem["code"], extra: Partial<Problem> = {}): ApiError =>
  new ApiError(status, { status, code, title: "x", type: "about:blank", ...extra });

describe("screenForGate", () => {
  it("routes each gate to its screen", () => {
    expect(screenForGate("open")).toBeNull();
    expect(screenForGate("set_pin")).toBe("set_pin");
    expect(screenForGate("enter_pin")).toBe("enter_pin");
    expect(screenForGate("idle_locked")).toBe("idle_locked");
    expect(screenForGate("pin_locked")).toBe("pin_locked");
  });
});

describe("the PIN to type", () => {
  it("asks for six digits in words", () => {
    expect(PIN_NEEDED).toBe("Enter your 6-digit PIN.");
  });

  it("tells a wrong PIN from every other refusal", () => {
    expect(isPinRefusal(problem(403, "pin_wrong", { tries_left: 3 }))).toBe(true);
    expect(isPinRefusal(problem(403, "forbidden"))).toBe(false);
    expect(isPinRefusal(problem(409, "note_locked"))).toBe(false);
    expect(isPinRefusal(new Error("offline"))).toBe(false);
  });
});

describe("pinProblemMessage", () => {
  it("counts the tries left, in the plural", () => {
    expect(pinProblemMessage(problem(403, "pin_wrong", { tries_left: 4 }), false)).toBe(
      "Wrong PIN. 4 tries left.",
    );
    expect(pinProblemMessage(problem(403, "pin_wrong", { tries_left: 2 }), true)).toBe(
      "Wrong PIN. 2 tries left.",
    );
  });

  it("says 1 try left in the singular, and warns a demo person that the next one ends the session", () => {
    expect(pinProblemMessage(problem(403, "pin_wrong", { tries_left: 1 }), true)).toBe(
      "Wrong PIN. 1 try left. Another wrong PIN ends this demo session.",
    );
  });

  it("says just wrong when the server did not count", () => {
    expect(pinProblemMessage(problem(403, "pin_wrong"), false)).toBe("Wrong PIN.");
  });

  it("shows the server's words for a bad PIN on the pin field", () => {
    const error = problem(422, "invalid_request", {
      errors: [{ field: "body.pin", message: "Choose a stronger PIN." }],
    });
    expect(pinProblemMessage(error, false)).toBe("Choose a stronger PIN.");
  });

  it("says the PIN is locked", () => {
    expect(pinProblemMessage(problem(423, "pin_locked"), false)).toBe(PIN_LOCKED);
    expect(PIN_LOCKED).toBe("Your PIN is locked. Ask a head nurse or the admin to reset it.");
  });

  it("falls back to a plain connection message for anything else", () => {
    expect(pinProblemMessage(new Error("offline"), false)).toBe(PIN_CONNECTION);
    expect(pinProblemMessage(problem(500, "invalid_request"), false)).toBe(PIN_CONNECTION);
    expect(
      pinProblemMessage(
        problem(422, "invalid_request", { errors: [{ field: "body.other", message: "no" }] }),
        false,
      ),
    ).toBe(PIN_CONNECTION);
  });

  it("warns a Google user on the last try that another wrong PIN locks it until a reset", () => {
    expect(pinProblemMessage(problem(403, "pin_wrong", { tries_left: 1 }), false)).toBe(
      "Wrong PIN. 1 try left. Another wrong PIN locks it until a head nurse or the admin resets it.",
    );
    expect(pinProblemMessage(problem(403, "pin_wrong", { tries_left: 2 }), false)).toBe(
      "Wrong PIN. 2 tries left.",
    );
  });

  it("says the session changed on a 409 (opened or set in another window)", () => {
    expect(pinProblemMessage(problem(409, "invalid_request"), false)).toBe(PIN_CHANGED);
    expect(pinProblemMessage(problem(409, "pin_already_set"), false)).toBe(PIN_CHANGED);
  });

  it("explains the ended demo session", () => {
    expect(DEMO_ENDED).toBe(
      "That was the fifth wrong PIN, so the demo session ended. Choose a person to start again.",
    );
  });
});

describe("demoEndedReason", () => {
  const wrongAtOne = problem(403, "pin_wrong", { tries_left: 1 });
  const unauthorized = problem(401, "not_signed_in");

  it("is the fifth wrong PIN only when the try before it was the last one", () => {
    expect(demoEndedReason(unauthorized, wrongAtOne)).toBe("fifth");
  });

  it("is an expired session for any other 401, and nothing for other answers", () => {
    expect(demoEndedReason(unauthorized, null)).toBe("expired");
    expect(demoEndedReason(unauthorized, problem(403, "pin_wrong", { tries_left: 3 }))).toBe(
      "expired",
    );
    expect(demoEndedReason(problem(403, "pin_wrong", { tries_left: 1 }), null)).toBeNull();
    expect(demoEndedReason(new Error("offline"), null)).toBeNull();
    expect(DEMO_EXPIRED).toBe("Your demo session ended. Choose a person to start again.");
  });
});

describe("idleLockWords", () => {
  it("says the wait in minutes, or seconds under a minute", () => {
    expect(idleLockWords(300)).toBe("Locked after 5 minutes without use.");
    expect(idleLockWords(60)).toBe("Locked after 1 minute without use.");
    expect(idleLockWords(90)).toBe("Locked after 2 minutes without use.");
    expect(idleLockWords(30)).toBe("Locked after 30 seconds without use.");
    expect(idleLockWords(1)).toBe("Locked after 1 second without use.");
  });
});

describe("isPinTyped", () => {
  it("is true only for exactly six digits", () => {
    expect(isPinTyped("246813")).toBe(true);
    expect(isPinTyped("24681")).toBe(false);
    expect(isPinTyped("2468130")).toBe(false);
    expect(isPinTyped("24681a")).toBe(false);
  });
});
