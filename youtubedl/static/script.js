document.body.classList.add("dark-theme");

/**
 * Extract the YouTube video ID from a URL.
 * Supports standard, shortened, and shorts URLs.
 */
function extractVideoId(url) {
  try {
    const urlObj = new URL(url.trim());
    if (urlObj.hostname === "youtu.be") {
      return urlObj.pathname.slice(1);
    }
    if (urlObj.hostname.includes("youtube.com")) {
      if (urlObj.pathname === "/watch") {
        return urlObj.searchParams.get("v");
      } else if (urlObj.pathname.startsWith("/shorts/")) {
        return urlObj.pathname.split("/")[2];
      }
    }
  } catch (e) {
    return null;
  }
  return null;
}

async function downloadVideos() {
  const inputField = document.getElementById("videoUrls");
  const progressBar = document.getElementById("progressBar");
  const progressText = document.getElementById("progressText");
  const progressContainer = document.getElementById("progressContainer");
  const videoList = document.getElementById("videoList");
  const resultDiv = document.getElementById("result");

  resultDiv.innerHTML = "";
  progressBar.style.width = "0%";
  progressText.innerText = "";
  videoList.innerHTML = "";

  // Show the progress container with animation
  progressContainer.classList.add("visible");

  const videoUrls = inputField.value.trim();
  if (!videoUrls) {
    resultDiv.innerHTML =
      '<p class="error">Please enter at least one YouTube URL.</p>';
    return;
  }

  // Start the download job via POST
  const response = await fetch("/api/download", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ videoUrls }),
  });
  const data = await response.json();
  if (!response.ok) {
    resultDiv.innerHTML = `<p class="error">${
      data.error || "Download failed."
    }</p>`;
    return;
  }

  const jobId = data.job_id;
  // Open SSE connection to receive progress updates
  const evtSource = new EventSource(`/api/progress/${jobId}`);
  evtSource.onmessage = function (e) {
    try {
      const jobData = JSON.parse(e.data);
      const progress = jobData.progress || {};

      // Update progress bar and text if progress exists
      if (progress.percent !== undefined) {
        progressBar.style.width = progress.percent + "%";
        const downloadedMB = (progress.downloaded / (1024 * 1024)).toFixed(2);
        const totalMB = (progress.total / (1024 * 1024)).toFixed(2);
        progressText.innerText = `${progress.percent}% (${downloadedMB} MB / ${totalMB} MB)`;
      }

      // Display video titles with uploader (if available) above the progress bar.
      if (jobData.videos && jobData.videos.length > 0) {
        const titles = jobData.videos.map((video) => {
          return video.uploader
            ? `${video.title} (${video.uploader})`
            : video.title;
        });
        videoList.innerHTML = `<strong>Download:</strong> ${titles.join(", ")}`;
      }

      // When complete, trigger file download
      if (jobData.completed && jobData.download_url) {
        evtSource.close();
        window.location.href = jobData.download_url;
      }
      if (jobData.error) {
        evtSource.close();
        resultDiv.innerHTML = `<p class="error">${jobData.error}</p>`;
      }
    } catch (err) {
      console.error("Error parsing progress data:", err);
    }
  };

  evtSource.onerror = function (err) {
    console.error("EventSource failed:", err);
    evtSource.close();
  };
}

function toggleTheme() {
  const body = document.body;
  if (body.classList.contains("dark-theme")) {
    body.classList.remove("dark-theme");
    body.classList.add("light-theme");
  } else {
    body.classList.remove("light-theme");
    body.classList.add("dark-theme");
  }
}
