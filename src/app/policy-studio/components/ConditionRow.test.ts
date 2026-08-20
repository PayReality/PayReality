import { describe, expect, it } from "vitest";
import { parseValue, valueToInputString } from "./ConditionRow";

// parseValue decides what value a Runtime Policy condition actually
// enforces server-side (a compiled Rego rule reads this exact value) --
// a coercion bug here silently changes what a rule does, not just how
// it displays. These lock in the real coercion rules for every operator.

describe("parseValue", () => {
  it("keeps 'exists' values as a strict boolean, not a truthy string check", () => {
    expect(parseValue("true", "exists")).toBe(true);
    expect(parseValue("false", "exists")).toBe(false);
    expect(parseValue("yes", "exists")).toBe(false); // only the literal string "true" is true
  });

  it("splits and trims an 'in' list", () => {
    expect(parseValue("US, CA,  MX", "in")).toEqual(["US", "CA", "MX"]);
  });

  it("coerces a numeric-looking value to a real number for numeric operators", () => {
    expect(parseValue("500", "<=")).toBe(500);
    expect(parseValue("500", "<=")).not.toBe("500");
    expect(parseValue("-12.5", ">")).toBe(-12.5);
  });

  it("does not coerce an empty string to 0", () => {
    expect(parseValue("", "<=")).toBe("");
  });

  it("coerces the literal strings 'true'/'false' to booleans for non-exists operators", () => {
    expect(parseValue("true", "==")).toBe(true);
    expect(parseValue("false", "!=")).toBe(false);
  });

  it("leaves a non-numeric, non-boolean string as-is", () => {
    expect(parseValue("wire_transfer", "==")).toBe("wire_transfer");
  });

  it("does not silently drop a leading zero into a different number", () => {
    // "010" -> Number("010") is 10, not 8 or NaN -- confirms no accidental
    // octal parsing and that this is a real, deliberate coercion, not an
    // incidental one worth losing track of.
    expect(parseValue("010", "==")).toBe(10);
  });
});

describe("valueToInputString", () => {
  it("joins an array value with a comma for display", () => {
    expect(valueToInputString(["US", "CA", "MX"])).toBe("US, CA, MX");
  });

  it("round-trips a plain string value", () => {
    expect(valueToInputString("wire_transfer")).toBe("wire_transfer");
  });

  it("round-trips a number back through parseValue unchanged", () => {
    const display = valueToInputString(500);
    expect(parseValue(display, "<=")).toBe(500);
  });
});
