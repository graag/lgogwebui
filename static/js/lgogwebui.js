function toggle_platform(game, platform) {
    $.get("/platform/"+game+"/"+platform, function(data){
        $("#"+game+"_platform_"+platform).toggleClass("disabled")
    })
    .fail(function() {
        alert( "error" );
    });
}
