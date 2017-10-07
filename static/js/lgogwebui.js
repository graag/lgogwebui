var active_games = []

function toggle_platform(game, platform) {
    $.get("/platform/"+game+"/"+platform, function(data){
        $("#"+game+"_platform_"+platform).toggleClass("disabled");
        console.log( "Toggle result: " + data )
        if(data.missing) {
            $("#"+game+"_download").show();
        } else {
            $("#"+game+"_download").hide();
        }
    })
    .fail(function(jqXHR, textStatus, errorThrown) {
        alert( textStatus );
    });
}

function game_download(game) {
    console.log( "start download" );
    $.get("/download/"+game, function(data){
        console.log( "download scheduled" );
        active_games.push(game)
        $("#"+game+"_progress").show();
        $("#"+game+"_spinner").show();
        $("#"+game+"_download").hide();
        $("#"+game+"_update").hide();
    })
    .fail(function(data) {
        alert( data );
    });
}

function executeQuery() {
    console.log("Query active downloads: " + active_games);
    if(active_games.length > 0) {
        $.ajax({
            url: '/status',
            type: 'POST',
            data: JSON.stringify(active_games),
            contentType: 'application/json; charset=utf-8',
            dataType: 'json',
            async: false,
            success: function(data) {
                console.log(data)
                Object.keys(data).forEach(function(game) {
                    console.log(game)
                    if (data[game].state === 'running') {
                        console.log("Active download - update")
                        $("#"+game+"_progress").find("span").text(data[game].progress+" %");
                    } else if (data[game].state === 'done') {
                        console.log("Download finished")
                        $("#"+game+"_progress").find("span").text(data[game].progress+" %");
                        $("#"+game+"_progress").hide();
                        $("#"+game+"_spinner").hide();
                        $("#"+game+"_repo").show();
                        const index = active_games.indexOf(game);
                        active_games.splice(index, 1);
                    }
                });
            }
        });
    }
    setTimeout(executeQuery, 5000); // you could choose not to continue on failure...
}

$(document).ready(function() {
    $.ajax({
        url: '/status',
        success: function(data) {
            active_games = data;
            console.log("Current active downloads: " + active_games);
        }
    })
    .fail(function() {
        alert( "error" );
    });
    // run the first time; all subsequent calls will take care of themselves
    setTimeout(executeQuery, 5000);
});
