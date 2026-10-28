import { BEACON_ALPHABET } from '../audio/beacon';

const LETTERS = BEACON_ALPHABET.slice(0, 26);

// The key's letters without repeats, then the rest of A to Z, as in
// cipher_alphabet() in signals.py. Each letter maps on its own, so a letter
// the phone misses does not garble the rest of a sealed message.
export function cipherAlphabet(key: string): string {
  return [...new Set([...key.toUpperCase(), ...LETTERS].filter((char) => LETTERS.includes(char)))].join('');
}

export function unseal(text: string, key: string): string {
  const cipher = cipherAlphabet(key);
  return [...text].map((char) => cipher.includes(char) ? LETTERS[cipher.indexOf(char)] : char).join('');
}
