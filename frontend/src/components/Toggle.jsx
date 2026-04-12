/**
 * Accessible, animated toggle switch.
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
        'relative inline-flex h-[22px] w-10 shrink-0 rounded-full',
        'border-2 border-transparent outline-none',
        'transition-colors duration-200 ease-in-out',
        checked ? 'bg-accent' : 'bg-white/15',
        disabled ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer hover:opacity-90',
      ].join(' ')}
    >
      <span
        className={[
          'pointer-events-none inline-block h-[18px] w-[18px] rounded-full bg-white',
          'shadow-sm',
          'transition-transform duration-200 ease-in-out',
          checked ? 'translate-x-[18px]' : 'translate-x-0',
        ].join(' ')}
      />
    </button>
  );
}
