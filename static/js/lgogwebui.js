var active_games = []
var user_status = ""
var download_filter = false

function toggle_platform(game, platform) {
    $.get("/platform/"+game+"/"+platform, function(data){
        $("#"+game+"_platform_1").addClass("selected");
        $("#"+game+"_platform_2").addClass("selected");
        $("#"+game+"_platform_4").addClass("selected");
        $("#"+game+"_platform_"+platform).toggleClass("disabled");
        console.log( "Toggle result: " + data )
        if(data.missing) {
            $("#"+game+"_download").show();
        } else {
            $("#"+game+"_download").hide();
        }
    })
    .fail(function(jqXHR, textStatus, errorThrown) {
        console.log(textStatus)
        alert( textStatus );
    });
}

function toggle_default_platform(platform) {
    $.get("/default_platform/"+platform, function(data){
        $("#platform_"+platform).toggleClass("disabled");
        Object.keys(data).forEach(function(game) {
            console.log( "Toggle " + game + " :missing=" + data[game].missing )
            $("#"+game+"_platform_"+platform).toggleClass("disabled");
            if(data[game].missing) {
                $("#"+game+"_download").show();
            } else {
                $("#"+game+"_download").hide();
            }
        })
    })
    .fail(function(jqXHR, textStatus, errorThrown) {
        console.log(textStatus)
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
    .fail(function(jqXHR, textStatus, errorThrown) {
        console.log(textStatus)
        alert( textStatus );
    });
}

function game_stop(game) {
    console.log( "stop download" );
    $.get("/stop/"+game, function(data){
        console.log( "stop requested" );
        $("#"+game+"_progress").hide();
        $("#"+game+"_spinner").hide();
        $("#"+game+"_download").show();
        $("#"+game+"_update").hide();
        $("#"+game+"_repo").show();
        const index = active_games.indexOf(game);
        active_games.splice(index, 1);
    })
    .fail(function(jqXHR, textStatus, errorThrown) {
        console.log(textStatus)
        alert( textStatus );
    });
}

function execute_query() {
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
                if(active_games.length > 0) {
                    $("#download_count").text(active_games.length.toString());
                    $("#download_status").show();
                } else {
                    $("#download_count").text("0");
                    if(!download_filter) {
                        $("#download_status").hide();
                    }
                }
            }
        });
    }
    $.get("/user_status", function(data){
        if(user_status != data.user_status) {
            console.log(data.user_status)
            user_status = data.user_status
            if(data.user_status === "running_2fa") {
                $("#user_icon").find("i").attr('class','fas fa-spinner fa-spin');
                $("#user_icon").find("span").text("Login in progress ...");
                document.getElementById('2fa').style.display='block'
            } else if (data.user_status === "logon") {
                $("#user_icon").find("i").attr('class','fas fa-user');
                $("#user_icon").find("span").text("Logged to GOG.com");
            } else if (data.user_status === "recaptcha") {
                $("#user_icon").find("i").attr('class','far fa-clock');
                $("#user_icon").find("span").text("Login requires solving reCAPTCHA. Try again later ...");
            } else if (data.user_status === "running") {
                $("#user_icon").find("i").attr('class','fas fa-spinner fa-spin');
                $("#user_icon").find("span").text("Login in progress ...");
            } else {
                $("#user_icon").find("i").attr('class','fas fa-user-slash');
                $("#user_icon").find("span").text("GOG.com login required");
                document.getElementById('login').style.display='block'
            }
        }
    })
    .fail(function(jqXHR, textStatus, errorThrown) {
        console.log(jqXHR)
        console.log(textStatus)
        console.log(errorThrown)
        alert( textStatus );
    });
    setTimeout(execute_query, 5000); // you could choose not to continue on failure...
}

function filter_games(){
    var $games = $(".game");

    $('#game_filter').keyup(function(){
        var val = '^(?=.*\\b' + $.trim($(this).val()).split(/\s+/).join('\\b)(?=.*\\b') + ').*$',
        reg = RegExp(val, 'i'),
        text;

        $games.show().filter(function(){
            text = $(this).text().replace(/\s+/g, ' ');
            return !reg.test(text);
        }).hide();

        $('#game_clear').show()
        download_filter = false
    });
}

function clear_filter(){
    $('#game_filter').val('')
    $('#game_clear').hide()
    $(".game").show()
}

function filter_downloads(){
    if(download_filter) {
        download_filter = false
        $(".game").show()
        if(active_games.length == 0) {
            $("#download_status").hide();
        }
    } else {
        clear_filter()
        download_filter = true
        $(".game").hide()
        active_games.forEach(function(game) {
            $("#" + game).show()
        })
    }
}

$(document).ready(function() {
    // Get the modal
    var modal = document.getElementById('login');
    var modal2 = document.getElementById('2fa');

    // When the user clicks anywhere outside of the modal, close it
    window.onclick = function(event) {
        if (event.target == modal) {
            modal.style.display = "none";
        }
        if (event.target == modal2) {
            modal2.style.display = "none";
        }
    }
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
    filter_games();
    // run the first time; all subsequent calls will take care of themselves
    setTimeout(execute_query, 5000);
});
