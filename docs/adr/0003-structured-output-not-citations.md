# 3. Structured output and our own quote check, not the Citations API

Date: 2026-11-13

## Status

Accepted

## Context

Every line of an AI-drafted FDAR note must point at the nurse's own words. The screen highlights
those words, and code decides each line's status before she signs, so a line with no support in
her note is visible as such.

The model API offers two ways to get structure and sources:

- **Citations.** The API returns cited text with character offsets into a document block. It can't
  be combined with structured output: a request that asks for both gets a 400 error. The draft
  would arrive as free text split into cited blocks, and code would have to parse those blocks into
  focus, data, action and response. The offsets also point into the document the model saw, which is
  the redacted note (known identifiers replaced by tokens), not the note the nurse typed.
- **Structured output.** The model returns JSON that follows a schema. Each line has its text, its
  source quotes as plain strings and an `own_wording` flag. The schema is the same for every
  patient and holds no patient data in an enum, a const or a pattern, because the API caches
  schemas apart from the messages.

## Decision

We use structured output and check the quotes ourselves.

- **The shape is the schema's job.** The provider sends the schema built from the `ModelFdarDraft`
  model as a JSON-schema output format. It calls `messages.create` and validates the text itself,
  not `messages.parse`, because `parse` validates before the stop reason can be read, so a refusal
  would show up as "invalid output" instead of "the model refused".
- **Quotes are plain text.** After the answer comes back, code restores the identifier tokens, then
  finds each quote in the note the nurse typed. Matching ignores case, spacing, curly quotes and
  Unicode forms, keeps a map back to the typed characters, and never matches inside a longer word
  or number. The result is stored as code-point spans into the typed note.
- **Numbers and units are read by code.** Every number in a line is compared by value with the
  numbers in its source, and every unit is compared through an alias table. Code never converts
  units.
- **Code sets each line's status, not the model.** The statuses are `no_source`, `number_mismatch`,
  `summary` and `source_found`; when more than one applies, the earlier one in that list wins.

## Consequences

- The schema guarantees the draft's shape, so no code parses free text into sections.
- The quote check is plain code, covered by unit and property tests, and the demo cases pin its
  output. We can test it without calling the model.
- A quote the model paraphrases or invents finds no match and the line is flagged `no_source`
  instead of being trusted.
- The same check runs for the fake, replay and live providers, and would run for a provider on
  another platform, because it depends only on the schema and the typed note.
- A meaning error, such as the right words read the wrong way, isn't caught for each draft. It is
  left to evaluation against the gold set.

## Alternatives considered

- **Citations with a parser on top.** Rejected for the two reasons above: it can't be combined with
  structured output, and its offsets are into the redacted note, so we would need a second mapping
  back to the typed note anyway.
- **Trusting the model's quotes without a check.** A quote that looks right but isn't in the note
  would be shown as sourced, which is the failure the nurse can least see.
