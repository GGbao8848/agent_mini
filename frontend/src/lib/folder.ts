/** Working-folder label helpers shared by the picker and the composer control. */

/** The folder every conversation works in unless it is bound to one. */
export const DEFAULT_FOLDER_LABEL = "default"

/** Menu action that unbinds a conversation (back to the default folder). */
export const FOLDER_NONE_LABEL = `回到 ${DEFAULT_FOLDER_LABEL} 文件夹`

/** Last path component (the folder's display name); "" for an empty path. */
export function folderBasename(path: string): string {
  return path.split(/[\\/]/).filter(Boolean).pop() ?? ""
}
