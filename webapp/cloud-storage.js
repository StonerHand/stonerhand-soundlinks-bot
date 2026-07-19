export function createCloudStorage(storage) {
  function get(key, callback) {
    try { storage?.getItem(key, (error, value) => callback(error, value)); }
    catch (error) { callback(error, null); }
  }

  function set(key, value, callback) {
    try { storage?.setItem(key, value, callback); }
    catch (error) { if (callback) callback(error); }
  }

  function remove(key, callback) {
    try {
      if (storage?.removeItem) storage.removeItem(key, callback);
      else set(key, "", callback);
    } catch (error) { if (callback) callback(error); }
  }

  return { get, set, remove };
}
