/**
 * Accessible, animated toggle switch.
 * Replaces native <input type="checkbox"> for a polished look.
 */
export default function Toggle({ checked, onChange, disabled = false }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => !disabled && onChange(!checked)}
      className={[
        'relative inline-flex h-6 w-11 shrink-0 rounded-full',
        'border-2 border-transparent outline-none',
        'transition-colors duration-200 ease-in-out',
        checked ? 'bg-accent shadow-[0_0_8px_rgba(134,199,234,0.35)]' : 'bg-[#b9c6d3]',
        disabled ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer hover:opacity-90',
      ].join(' ')}
    >
      <span
        className={[
          'pointer-events-none inline-block h-5 w-5 rounded-full bg-[#f3f5f7]',
          'shadow-[0_1px_4px_rgba(0,0,0,0.35),0_0_0_1px_rgba(0,0,0,0.05)]',
          'transition-transform duration-200 ease-in-out',
          checked ? 'translate-x-5' : 'translate-x-0',
        ].join(' ')}
      />
    </button>
  );
}
