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
  const filePicker = document.getElementById("file");

  function SubmitOnEnter(editor) {
    editor.editing.view.document.on("enter", (evt, data) => {
      if (data.isSoft) {
        return;
      }
      data.preventDefault();
      evt.stop();
      document.querySelector(`#${formId} > input[name=msg]`).value =
        editor.getData();
      htmx.trigger(`#${formId}`, "submit");
      editor.setData("");
      document.querySelector(`#${formId} > input[name=msg]`).value = null;

      // clear attachments
      const attachments = document.getElementById("attachments");
      while (attachments.firstChild) {
        attachments.removeChild(attachments.firstChild);
      }

      // locate all hidden inputs that start with "upload" and remove them
      document
        .querySelectorAll(`#${formId} > input[type=hidden][name^="upload"]`)
        .forEach((el) => el.remove());
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
  }).then((editor) => {
    filePicker.addEventListener("change", () =>
      htmx.trigger(`#${formId}_upload`, "submit")
    );

    document
      .getElementById(`${formId}_upload_pick`)
      .addEventListener("click", () => {
        filePicker.click();
      });

    document.body.addEventListener("htmx:beforeRequest", function (evt) {
      if (evt.detail.requestConfig.path === "/upload") {
        editor.enableReadOnlyMode(
          `upload-${evt.detail.requestConfig.triggeringEvent.timeStamp}`
        );
      }
    });

    document.body.addEventListener("htmx:afterSettle", function (evt) {
      if (evt.detail.requestConfig.path === "/upload") {
        editor.disableReadOnlyMode(
          `upload-${evt.detail.requestConfig.triggeringEvent.timeStamp}`
        );
        // clear the file input
        filePicker.value = null;
      }
    });

    editor.editing.view.focus();
  });
}
