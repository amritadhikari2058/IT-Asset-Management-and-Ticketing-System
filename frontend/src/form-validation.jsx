/** Shared form validation primitives and a reusable form state hook.
 *
 * Provides:
 *  - validation rules (required, email, minLength, maxLength, pattern, confirm)
 *  - validateSchema(values, rules) -> { errors } object keyed by field name
 *  - useFormState(initialValues, validateOnChange) -> { values, errors, setField, isDirty, reset, handleSubmit }
 *
 * Usage:
 *   const rules = { title: [required(), minLength(3)], email: [required(), email()] };
 *   const { values, errors, setField, handleSubmit } = useFormState(initial, rules);
 *   <Field label="Title" error={errors.title}><input ... onChange={(e)=>setField('title',e.target.value)} /></Field>
 */

export const required = (msg = 'This field is required.') => (v) =>
  v == null || String(v).trim() === '' ? msg : null;

export const minLength = (n, msg = null) => (v) => {
  if (v == null || String(v).trim() === '') return null;
  return String(v).trim().length < n ? (msg || `Must be at least ${n} characters.`) : null;
};

export const maxLength = (n, msg = null) => (v) => {
  if (v == null || String(v).trim() === '') return null;
  return String(v).trim().length > n ? (msg || `Must be no more than ${n} characters.`) : null;
};

export const email = (msg = 'Enter a valid email address.') => (v) => {
  if (v == null || String(v).trim() === '') return null;
  const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  return re.test(String(v)) ? null : msg;
};

export const pattern = (re, msg = 'Invalid format.') => (v) => {
  if (v == null || String(v).trim() === '') return null;
  return re.test(String(v)) ? null : msg;
};

export const confirm = (fieldName, getOther, msg = 'Values do not match.') => (v) => {
  if (v == null || String(v).trim() === '') return null;
  const other = getOther ? getOther() : undefined;
  return String(v) === String(other) ? null : msg;
};

/** Validate an object of values against an object of field rules.
 *  Returns { errors } where errors[field] is the first error message or null. */
export function validateSchema(values, rules) {
  const errors = {};
  for (const [field, fieldRules] of Object.entries(rules)) {
    if (!Array.isArray(fieldRules)) continue;
    for (const rule of fieldRules) {
      const err = rule(values[field], values);
      if (err) { errors[field] = err; break; }
    }
  }
  return errors;
}

/** hasError helper for Field components. */
export function fieldError(errors, field) {
  return errors[field] || null;
}
