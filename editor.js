import {
  ClassicEditor,
  AccessibilityHelp,
  AutoLink,
  Autosave,
  Bold,
  Essentials,
  Italic,
  Link,
  Markdown,
  Paragraph,
  SelectAll,
} from "ckeditor5";

export default function ($el, { placeholder, formId }) {
  function SubmitOnEnter(editor) {
    editor.editing.view.document.on("enter", (evt, data) => {
      if (data.isSoft) {
        return;
      }
      data.preventDefault();
      evt.stop();
      document.querySelector(`#${formId} > input[type=hidden]`).value =
        editor.getData();
      htmx.trigger(`#${formId}`, "submit");
      editor.setData("");
      document.querySelector(`#${formId} > input[type=hidden]`).value = null;
    });
  }

  ClassicEditor.create($el, {
    toolbar: {
      items: ["bold", "italic", "link"],
      shouldNotGroupWhenFull: false,
    },
    plugins: [
      AccessibilityHelp,
      AutoLink,
      Autosave,
      Bold,
      Essentials,
      Italic,
      Link,
      Markdown,
      Paragraph,
      SelectAll,
      SubmitOnEnter,
    ],
    link: {
      addTargetToExternalLinks: true,
      defaultProtocol: "https://",
    },
    placeholder,
  }).then((editor) => editor.editing.view.focus());
}
