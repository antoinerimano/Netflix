// src/components/ProfileAgeFields.js
// "Kids profile" switch + age limit, shared by the profile create / edit forms.
// Backend rules: users/maturity.py (a Kids profile never goes above PG).
import React from "react";

const AGE_OPTIONS = [
  { value: "G", label: "G - all ages" },
  { value: "PG", label: "PG" },
  { value: "PG-13", label: "PG-13" },
  { value: "R", label: "R" },
  { value: "NC-17", label: "No limit" },
];
const KIDS_OPTIONS = ["G", "PG"];

export default function ProfileAgeFields({ profile, onChange, labelClassName, selectClassName }) {
  const isKids = !!profile.is_kids;
  const age = profile.age_restriction || "NC-17";
  const options = isKids ? AGE_OPTIONS.filter((o) => KIDS_OPTIONS.includes(o.value)) : AGE_OPTIONS;

  const toggleKids = (checked) => {
    // switching to Kids: bring the limit down to G unless it is already a kids limit
    onChange({ is_kids: checked, age_restriction: checked && !KIDS_OPTIONS.includes(age) ? "G" : age });
  };

  return (
    <>
      <label className={labelClassName}>
        <input type="checkbox" checked={isKids} onChange={(e) => toggleKids(e.target.checked)} /> Kids profile
      </label>
      <label className={labelClassName}>
        Age Restriction{labelClassName ? "" : ":"}
        <select
          value={isKids && !KIDS_OPTIONS.includes(age) ? "G" : age}
          onChange={(e) => onChange({ age_restriction: e.target.value })}
          className={selectClassName}
        >
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </label>
    </>
  );
}

export function describeAgeLimit(profile) {
  if (profile?.is_kids) return `Kids (${profile.age_restriction === "PG" ? "PG" : "G"})`;
  const opt = AGE_OPTIONS.find((o) => o.value === profile?.age_restriction);
  return opt ? opt.label : "No limit";
}
